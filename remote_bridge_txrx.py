#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import re
import sys
import threading
import pigpio

# ============================
# CONFIG
# ============================

COOLDOWN_SEC = 0.35
DEBUG = True  # Set to True to print debug logs for RX signals

# ============================
# TX CODES (blinds)
# ============================

w7_down  = '20000000001000110111100010011011100110011'
w7_up    = '20000000001000110111100010011011100010001'
w7_stop  = '20000000001000110111100010011011101010101'

w8_down  = '20000000001000110111100010011100000110011'
w8_up    = '20000000001000110111100010011100000010001'
w8_stop  = '20000000001000110111100010011100001010101'

w9_down  = '20000000001000110111100010011100100110011'
w9_up    = '20000000001000110111100010011100100010001'
w9_stop  = '20000000001000110111100010011100101010101'

# ============================
# TX TIMING
# ============================

FIRST_BLOCK_ON   = 0.00362
SHORT_DELAY      = 0.000362
LONG_DELAY       = 0.000724
FIRST_BLOCK_OFF  = 0.00148
EXTENDED_DELAY   = 0.01137

NUM_ATTEMPTS = 5
TX_PIN = 23
RX_PIN = 27

# ============================
# BLIND TX LOOKUP
# ============================

BLIND_TX = {
    "w7": {"up": w7_up, "down": w7_down, "stop": w7_stop},
    "w8": {"up": w8_up, "down": w8_down, "stop": w8_stop},
    "w9": {"up": w9_up, "down": w9_down, "stop": w9_stop}
}

# ============================
# REMOTE MAP (ID + DATA)
# ============================

REMOTE_CODE_MAP = {
    "eb2dfb8": ("remote_hanna", "ch1", "up"),
    "eb2df78": ("remote_hanna", "ch1", "stop"),
    "eb2dfd8": ("remote_hanna", "ch1", "down"),
    
    "ea2dfb8": ("remote_hanna", "ch2", "up"),
    "ea2df78": ("remote_hanna", "ch2", "stop"),
    "ea2dfd8": ("remote_hanna", "ch2", "down"),

    "e92dfb8": ("remote_hanna", "ch3", "up"),
    "e92df78": ("remote_hanna", "ch3", "stop"),
    "e92dfd8": ("remote_hanna", "ch3", "down"),

    "ea2efb8": ("remote_janka", "ch1", "up"),
    "ea2ef78": ("remote_janka", "ch1", "stop"),
    "ea2efd8": ("remote_janka", "ch1", "down"),
}

# ============================
# (controller_id, channel) -> blinds
# ============================

CHANNEL_TO_TARGET = {
    ("remote_hanna", "ch1"): ["w8"],
    ("remote_hanna", "ch2"): ["w9"],
    ("remote_hanna", "ch3"): ["w8", "w9"],
    ("remote_janka", "ch1"): ["w7"],
}

# ============================
# pigpio INITIALIZATION
# ============================

pi = pigpio.pi()
if not pi.connected:
    print("\n[ERROR] Could not connect to pigpiod daemon.")
    print("Please make sure pigpiod is running. You can start it with:")
    print("  sudo systemctl enable pigpiod")
    print("  sudo systemctl start pigpiod\n")
    sys.exit(1)

# ============================
# STATE VARIABLES
# ============================

rx_lock = threading.Lock()
edge_buffer = []          # list of (tick, level) tuples for current capture
last_edge_time = 0.0

is_transmitting = False
last_tx_time = 0.0

raw_transition_count = 0
diag_mode = False         # set via --diag flag

# Pulse width histogram buckets for diagnostics
pulse_hist = {
    "<100": 0, "100-250": 0, "250-500": 0, "500-800": 0,
    "800-1200": 0, "1200-2000": 0, "2000-4000": 0,
    "4000-8000": 0, "8000+": 0
}

# ============================
# HELPER FUNCTIONS
# ============================

def log(msg: str):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

def classify_pulse(us):
    if us < 100: return "<100"
    if us < 250: return "100-250"
    if us < 500: return "250-500"
    if us < 800: return "500-800"
    if us < 1200: return "800-1200"
    if us < 2000: return "1200-2000"
    if us < 4000: return "2000-4000"
    if us < 8000: return "4000-8000"
    return "8000+"

def transmit_code(code: str):
    global is_transmitting, last_tx_time
    is_transmitting = True
    try:
        for _ in range(NUM_ATTEMPTS):
            for sym in code:
                if sym == '2':
                    pi.write(TX_PIN, 1); time.sleep(FIRST_BLOCK_ON)
                    pi.write(TX_PIN, 0); time.sleep(FIRST_BLOCK_OFF)
                elif sym == '1':
                    pi.write(TX_PIN, 1); time.sleep(LONG_DELAY)
                    pi.write(TX_PIN, 0); time.sleep(SHORT_DELAY)
                elif sym == '0':
                    pi.write(TX_PIN, 1); time.sleep(SHORT_DELAY)
                    pi.write(TX_PIN, 0); time.sleep(LONG_DELAY)
            pi.write(TX_PIN, 0)
            time.sleep(EXTENDED_DELAY)
    finally:
        is_transmitting = False
        last_tx_time = time.time()

def handle(remote_name: str, channel: str, action: str):
    targets = CHANNEL_TO_TARGET.get((remote_name, channel), [])
    if not targets:
        log(f"No targets for remote={remote_name}, channel={channel}")
        return

    repeat = 3 if action == 'up' else 1

    for blind_id in targets:
        tx_code = BLIND_TX.get(blind_id, {}).get(action)
        if not tx_code:
            log(f"No TX code for blind={blind_id} action={action}")
            continue

        log(f"TX -> remote={remote_name} blind={blind_id} action={action}")
        for _ in range(repeat):
            transmit_code(tx_code)
            time.sleep(0.05)

# ============================
# RX CALLBACK & DECODING
# ============================

def rx_callback(gpio, level, tick):
    """Gap-based framing: collect all edges; the timeout loop detects packet
    boundaries by looking for gaps > 2 ms between consecutive edges."""
    global last_edge_time, raw_transition_count

    raw_transition_count += 1

    # Ignore signals during transmission and shortly after
    if is_transmitting or (time.time() - last_tx_time) < 0.2:
        with rx_lock:
            edge_buffer.clear()
        return

    now_wall = time.time()

    with rx_lock:
        last_edge_time = now_wall
        edge_buffer.append((tick, level))
        # Safety cap – keep at most 500 edges in the buffer
        if len(edge_buffer) > 500:
            edge_buffer.pop(0)


def decode_edges(edges):
    """Given a list of (tick, level) edges, extract HIGH-pulse durations
    and decode them into bits.
    Returns (bit_string, high_pulses_us_list)."""
    high_pulses = []
    bits = []

    for i in range(1, len(edges)):
        duration = pigpio.tickDiff(edges[i-1][0], edges[i][0])
        prev_level_after = edges[i][1]  # level AFTER this edge

        # prev_level_after == 0 means we just had a falling edge,
        # so the interval was a HIGH pulse.
        if prev_level_after == 0:
            high_pulses.append(duration)

    # Now decode the HIGH pulses.
    # Look for preamble (>2000 us HIGH) followed by short/long data bits.
    preamble_idx = None
    for idx, p in enumerate(high_pulses):
        if p >= 2000:
            preamble_idx = idx
            # Don't break – take the LAST preamble in the burst
            # (earlier ones might be noise)

    if preamble_idx is not None:
        data_pulses = high_pulses[preamble_idx + 1:]
        for p in data_pulses:
            if 150 <= p <= 600:
                bits.append('0')
            elif 600 < p <= 1500:
                bits.append('1')
            else:
                break  # invalid pulse terminates the packet

    return "".join(bits), high_pulses


def check_timeout_loop():
    """Periodically checks if there's a gap > 5 ms since the last edge,
    indicating a packet boundary. Then decodes the collected edges."""
    global edge_buffer, last_edge_time
    last_cooldown_key = None
    last_ts = 0.0

    while True:
        time.sleep(0.008)  # Check every 8 ms

        with rx_lock:
            # If we have edges and no new edge for > 5 ms, process the burst
            if edge_buffer and (time.time() - last_edge_time) > 0.005:
                edges = list(edge_buffer)
                edge_buffer.clear()
            else:
                edges = None

        if not edges or len(edges) < 4:
            continue

        bit_str, high_pulses = decode_edges(edges)

        # In diagnostic mode, log all bursts
        if diag_mode:
            # Update histogram
            for p in high_pulses:
                bucket = classify_pulse(p)
                pulse_hist[bucket] += 1
            if len(high_pulses) >= 5:
                sample = high_pulses[:20]
                log(f"[DIAG] Burst: {len(edges)} edges, {len(high_pulses)} HIGH pulses. "
                    f"Sample HIGH durations (us): {sample}")
                if bit_str:
                    log(f"[DIAG]   Decoded {len(bit_str)} bits: {bit_str}")

        if not bit_str:
            continue

        if DEBUG and len(bit_str) >= 10:
            try:
                val = int(bit_str, 2)
                hex_val = f"{val:07x}"
            except ValueError:
                hex_val = "invalid"
            log(f"[DEBUG] RX Packet: {len(bit_str)} bits ({bit_str}) -> Hex: {hex_val}")

        if len(bit_str) == 28:
            try:
                val = int(bit_str, 2)
                data = f"{val:07x}"

                if data in REMOTE_CODE_MAP:
                    remote_name, channel, action = REMOTE_CODE_MAP[data]

                    cooldown_key = (remote_name, channel, action)
                    now = time.time()
                    if cooldown_key == last_cooldown_key and (now - last_ts) < COOLDOWN_SEC:
                        continue

                    last_cooldown_key = cooldown_key
                    last_ts = now

                    log(f"RX -> remote={remote_name} channel={channel} action={action} data={data}")
                    handle(remote_name, channel, action)
                else:
                    log(f"UNKNOWN 28-bit code: {data}")
            except Exception as e:
                log(f"Error decoding bits {bit_str}: {e}")

def heartbeat_loop():
    global raw_transition_count
    while True:
        time.sleep(5.0)
        count = raw_transition_count
        raw_transition_count = 0
        if DEBUG:
            log(f"[DEBUG] Heartbeat: {count} edges in last 5s")
        if diag_mode and any(v > 0 for v in pulse_hist.values()):
            hist_str = ", ".join(f"{k}: {v}" for k, v in pulse_hist.items() if v > 0)
            log(f"[DIAG] Pulse histogram: {hist_str}")
            for k in pulse_hist:
                pulse_hist[k] = 0

# ============================
# MAIN
# ============================

def main():
    global diag_mode

    # Pin modes setup
    pi.set_mode(TX_PIN, pigpio.OUTPUT)
    pi.write(TX_PIN, 0)

    # If the user wants to test TX:
    if len(sys.argv) > 1 and sys.argv[1] == "--test-tx":
        if len(sys.argv) < 4:
            print("Usage for TX test: python3 remote_bridge_txrx.py --test-tx <blind_id> <action>")
            print("Example: python3 remote_bridge_txrx.py --test-tx w7 up")
            pi.stop()
            sys.exit(1)
        blind_id = sys.argv[2]
        action = sys.argv[3]
        tx_code = BLIND_TX.get(blind_id, {}).get(action)
        if not tx_code:
            print(f"Error: Unknown blind={blind_id} or action={action}")
            pi.stop()
            sys.exit(1)

        log(f"TEST TX -> transmitting command for blind={blind_id} action={action}...")
        transmit_code(tx_code)
        log("Test transmission complete.")
        pi.stop()
        sys.exit(0)

    if "--diag" in sys.argv:
        diag_mode = True
        log(">>> DIAGNOSTIC MODE ENABLED – logging all pulse widths <<<")

    log("Starting direct GPIO RF bridge with pigpio (MX-RM-5V + Transmitter)")
    log(f"Allowed model/protocol: OOK_PWM (s=356us, l=1028us)")

    # Receiver Setup
    pi.set_mode(RX_PIN, pigpio.INPUT)
    pi.set_pull_up_down(RX_PIN, pigpio.PUD_DOWN)

    # Glitch filter: 100 us – low enough to preserve 356 us short pulses
    # but still eliminates sub-100us ringing
    pi.set_glitch_filter(RX_PIN, 100)
    log(f"Glitch filter: 100 us | RX pin: GPIO{RX_PIN} | TX pin: GPIO{TX_PIN}")

    # Setup Edge Interrupt Callback on RX Pin
    cb = pi.callback(RX_PIN, pigpio.EITHER_EDGE, rx_callback)

    # Start background checker thread
    t = threading.Thread(target=check_timeout_loop, daemon=True)
    t.start()

    # Start heartbeat thread
    tb = threading.Thread(target=heartbeat_loop, daemon=True)
    tb.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("Stopping (Ctrl+C)")
        pi.write(TX_PIN, 0)
        cb.cancel()
        pi.stop()

if __name__ == "__main__":
    main()
