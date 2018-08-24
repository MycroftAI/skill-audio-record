# Copyright 2016 Mycroft AI, Inc.
#
# This file is part of Mycroft Core.
#
# Mycroft Core is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Mycroft Core is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Mycroft Core.  If not, see <http://www.gnu.org/licenses/>.


import math
import time

import psutil as psutil
from os.path import dirname, exists
import os

from mycroft import (MycroftSkill, intent_handler, AdaptIntent,
        intent_file_handler)
from mycroft.util import record, play_wav
from mycroft.util.log import LOG

from mycroft.util.parse import extract_datetime
from mycroft.util.time import now_local


class AudioRecordSkill(MycroftSkill):
    def __init__(self):
        super(AudioRecordSkill, self).__init__("AudioRecordSkill")
        self.free_disk = self.config.get('free_disk')
        self.max_time = self.config.get('max_time')
        self.notify_delay = self.config.get('notify_delay')
        self.rate = self.config.get('rate')
        self.channels = self.config.get('channels')
        self.file_path = self.config.get('filename')
        self.duration = 0
        self.notify_time = None
        self.play_process = None
        self.record_process = None

    @intent_handler(AdaptIntent("AudioRecordSkillIntent").require("AudioRecordSkillKeyword"))
    def handle_record(self, message):
        utterance = message.data.get('utterance')
        now = now_local()
        stop_time, _ = extract_datetime(utterance, lang=self.lang)
        duration = (stop_time - now).total_seconds()
        if self.is_free_disk_space():
            self.feedback_start()
            time.sleep(3)
            self.record_process = record(
                self.file_path, int(duration), self.rate, self.channels)
            self.schedule_repeating_event(self.notify, now,
                                          self.notify_delay, name='notify')
        else:
            self.speak_dialog("audio.record.disk.full")

    def is_free_disk_space(self):
        space = self.duration * self.channels * self.rate / 1024 / 1024
        free_mb = psutil.disk_usage('/')[2] / 1024 / 1024
        if free_mb - space > self.free_disk:
            return True
        else:
            return False

    def feedback_start(self):
        if self.duration > 0:
            self.speak_dialog(
                'audio.record.start.duration', {'duration': self.duration})
        else:
            self.speak_dialog('audio.record.start')

    @intent_handler(AdaptIntent('AudioRecordSkillStopIntent').require(
        'AudioRecordSkillStopVerb') \
        .require('AudioRecordSkillKeyword'))
    def handle_stop(self, message):
        self.speak_dialog('audio.record.stop')
        self.cancel_scheduled_event('notify')
        if self.record_process:
            self.stop_process(self.record_process)
            self.record_process = None

    @intent_handler(AdaptIntent('AudioRecordSkillDeleteIntent') \
        .require('AudioRecordSkillDeleteVerb') \
        .require('AudioRecordSkillKeyword'))
    def handle_delete(self, message):
        if not exists(self.file_path):
            self.speak_dialog('audio.record.no.recording')
        else:
            try:
                os.remove(self.file_path)
                self.speak_dialog('audio.record.removed')
            except:
                pass

    @staticmethod
    def stop_process(process):
        if process.poll() is None:
            process.terminate()
            process.wait()

    def notify(self, timestamp):
        if self.record_process and self.record_process.poll() is None:
            if self.is_free_disk_space():
                LOG.info("Recording...")
            else:
                self.handle_stop(None)
                self.speak_dialog("audio.record.disk.full")
        else:
            self.handle_stop(None)

    @intent_file_handler('PlayRecording.intent')
    def handle_play(self, message):
        if exists(self.file_path):
            self.play_process = play_wav(self.file_path)
        else:
            self.speak_dialog('audio.record.no.recording')

    @intent_handler(AdaptIntent('AudioRecordSkillStopPlayIntent').require(
        'AudioRecordSkillStopVerb') \
        .require('AudioRecordSkillPlayVerb').require('AudioRecordSkillKeyword')
        )
    def handle_stop_play(self, message):
        self.speak_dialog('audio.record.stop.play')
        if self.play_process:
            self.stop()
            self.play_process = None
            return True
        return False

    def stop(self):
        if self.play_process:
            return self.stop_process(self.play_process)
        if self.record_process:
            return self.stop_process(self.record_process)


def create_skill():
    return AudioRecordSkill()
