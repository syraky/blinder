# -*- coding: utf-8 -*-
"""
Created on Sat Jan 28 19:10:37 2023

@author: Akos.Herdics
"""
import logging
import time
import RPi.GPIO as GPIO

c04   = '211100001010001001000011000100100' 
down  = '00110011'
up    = '00010001'
stop  = '01010101'

LOGGER = logging.getLogger(__name__)

class CoverInstance:
    def __init__(self, name, cover_name, action):
        self._name = name
        self._cover_name = cover_name
        self._action = action

    def transmit_code(self):
        '''Transmit a chosen code string using the GPIO transmitter'''
        cover_name = self._cover_name
        cover_action = self._action
        self.pin = 23
        self.NUM_ATTEMPTS = 5
        self.first_block_on_delay = 0.00362
        self.short_delay = 0.000362
        self.long_delay = 0.000724
        self.first_block_off_delay = 0.00148
        self.extended_delay = 0.01137

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pin, GPIO.OUT)
        self.code = cover_name + cover_action
        for t in range(self.NUM_ATTEMPTS):
            for i in self.code:
                if i == '2':
                    GPIO.output(self.pin, 1)
                    time.sleep(self.first_block_on_delay)
                    GPIO.output(self.pin, 0)
                    time.sleep(self.first_block_off_delay)
                elif i == '1':
                    GPIO.output(self.pin, 1)
                    time.sleep(self.long_delay)
                    GPIO.output(self.pin, 0)
                    time.sleep(self.short_delay)
                elif i == '0':
                    GPIO.output(self.pin, 1)
                    time.sleep(self.short_delay)
                    GPIO.output(self.pin, 0)
                    time.sleep(self.long_delay)
                else:
                    continue
            GPIO.output(self.pin, 0)
            time.sleep(self.extended_delay)
        GPIO.cleanup()

