#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import subprocess
import time
import re
import RPi.GPIO as GPIO

# ============================
# CONFIG
# ============================

# ALLOWED_MODEL = "Akhan-100F14"
ALLOWED_MODEL = "blind"
COOLDOWN_SEC = 0.35

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

GPIO.setmode(GPIO.BCM)
GPIO.setup(TX_PIN, GPIO.OUT)
GPIO.output(TX_PIN, 0)

def transmit_code(code: str):

    for _ in range(NUM_ATTEMPTS):
        for sym in code:
            if sym == '2':
                GPIO.output(TX_PIN, 1); time.sleep(FIRST_BLOCK_ON)
                GPIO.output(TX_PIN, 0); time.sleep(FIRST_BLOCK_OFF)
            elif sym == '1':
                GPIO.output(TX_PIN, 1); time.sleep(LONG_DELAY)
                GPIO.output(TX_PIN, 0); time.sleep(SHORT_DELAY)
            elif sym == '0':
                GPIO.output(TX_PIN, 1); time.sleep(SHORT_DELAY)
                GPIO.output(TX_PIN, 0); time.sleep(LONG_DELAY)
        GPIO.output(TX_PIN, 0)
        time.sleep(EXTENDED_DELAY)


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

# REMOTE_MAP = {
#     (85280, "0x4"): ("ch1", "up"),
#     (85280, "0x8"): ("ch1", "stop"),
#     (85280, "0x2"): ("ch1", "down"),

#     (89376, "0x4"): ("ch2", "up"),
#     (89376, "0x8"): ("ch2", "stop"),
#     (89376, "0x2"): ("ch2", "down"),

#     (93472, "0x4"): ("ch3", "up"),
#     (93472, "0x8"): ("ch3", "stop"),
#     (93472, "0x2"): ("ch3", "down"),

#     (89360, "0x4"): ("ch1", "up"),
#     (89360, "0x8"): ("ch1", "stop"),
#     (89360, "0x2"): ("ch1", "down"),
# }

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
# RTL_433
# ============================

# RTL_433_CMD = ["rtl_433", "-f", "433920000", "-M", "newmodel", "-F", "json"]
RTL_433_CMD = [
    "rtl_433",
    "-f", "433920000",
    "-g", "20",
    "-X", "n=blind,m=OOK_PWM,s=356,l=1028,r=984,g=0,t=269,y=0",
    "-F", "json",
]

def extract_hex(data_field: str):
    if not isinstance(data_field, str):
        return None
    m = re.search(r"0x[0-9a-fA-F]+", data_field)
    return m.group(0).lower() if m else None

def log(msg: str):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

# def handle(controller_id: int, channel: str, action: str):
#     targets = CHANNEL_TO_TARGET.get((controller_id, channel), [])
#     if not targets:
#         log(f"No targets for controller_id={controller_id}, channel={channel}")
#         return
#     repeat = 3 if action == 'up' else 1
    
#     for blind_id in targets:
#         tx_code = BLIND_TX.get(blind_id, {}).get(action)
#         if not tx_code:
#             log(f"No TX code for blind={blind_id} action={action}")
#             continue 

#         log(f"TX -> blind={blind_id} action={action}")
#         for _ in range(repeat):
#             transmit_code(tx_code)
#             time.sleep(0.05)

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
# MAIN
# ============================

def main():
    log("Starting rtl_433 bridge (multi-remote)")
    log(f"Allowed model: {ALLOWED_MODEL}")

    p = subprocess.Popen(
        RTL_433_CMD,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    last_cooldown_key = None
    last_ts = 0.0

    try:
        for line in p.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue

            try:
                msg = json.loads(line)
                log(f"RAW MSG: {msg}")
            except Exception:
                continue
                
            if msg.get("model") != ALLOWED_MODEL:
                continue

            data = None

            rows = msg.get("rows") or []
            if rows and isinstance(rows, list):
                first = rows[0] or {}
                data = first.get("data")

            if not data:
                codes = msg.get("codes") or []
                if codes and isinstance(codes, list):
                    raw_code = str(codes[0])
                    m = re.search(r"}([0-9a-fA-F]+)$", raw_code)
                    if m:
                        data = m.group(1)

            if not data:
                log(f"UNKNOWN MSG: {msg}")
                continue

            data = str(data).lower()

            if data not in REMOTE_CODE_MAP:
                log(f"UNKNOWN DATA: {data}")
                continue

            remote_name, channel, action = REMOTE_CODE_MAP[data]
            
            cooldown_key = (remote_name, channel, action)
            now = time.time()
            if cooldown_key == last_cooldown_key and (now - last_ts) < COOLDOWN_SEC:
                continue

            last_cooldown_key = cooldown_key
            last_ts = now

            log(f"RX -> remote={remote_name} channel={channel} action={action} data={data}")
            handle(remote_name, channel, action)

            # --- MODEL FILTER ---
#            if msg.get("model") != ALLOWED_MODEL:
#                continue

#            controller_id = msg.get("id")
#            data_hex = extract_hex(msg.get("data"))

#            if controller_id is None or data_hex is None:
#                continue

#            key = (controller_id, data_hex)
#            if key not in REMOTE_MAP:
#                log(f"UNKNOWN: id={controller_id} data={msg.get('data')}")
#                continue

#            channel, action = REMOTE_MAP[key]

#            cooldown_key = (controller_id, channel, action)
#            now = time.time()
#            if cooldown_key == last_cooldown_key and (now - last_ts) < COOLDOWN_SEC:
#                continue

#            last_cooldown_key = cooldown_key
#            last_ts = now

#            log(f"RX -> id={controller_id} channel={channel} action={action}")
#            handle(controller_id, channel, action)

    except KeyboardInterrupt:
        log("Stopping (Ctrl+C)")
        GPIO.output(TX_PIN, 0)
        GPIO.cleanup()
        
    finally:
        try:
            p.terminate()
        except Exception:
            pass

if __name__ == "__main__":
    main()
