# Copyright 2016, Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import time
import psutil as psutil
from os.path import dirname, exists

from adapt.intent import IntentBuilder
from mycroft import MycroftSkill, intent_handler, intent_file_handler
from mycroft.audio import wait_while_speaking, is_speaking
from mycroft.messagebus.message import Message
from mycroft.util import record, play_wav
from mycroft.util.parse import extract_datetime
from mycroft.util.time import now_local

class AudioRecordSkill(MycroftSkill):
    def __init__(self):
        super(AudioRecordSkill, self).__init__("AudioRecordSkill")
        self.play_process = None
        self.record_process = None
        self.start_time = 0
        self.last_index = 24  # index of last pixel in countdowns

        self.settings["min_free_disk"] = 100  # min mb to leave free on disk
        self.settings["rate"] = 16000  # sample rate, hertz
        self.settings["channels"] = 1  # recording channels (1 = mono)
        self.settings["file_path"] = "/tmp/mycroft-recording.wav"
        self.settings["duration"] = -1  # default = unknown

    def remaining_time(self):
        return self.settings["duration"] - (now_local() -
                                            self.start_time).total_seconds()

    def has_free_disk_space(self):
        space = (self.remaining_time() * self.settings["channels"] *
                 self.settings["rate"] / 1024 / 1024)
        free_mb = psutil.disk_usage('/')[2] / 1024 / 1024
        return free_mb - space > self.settings["min_free_disk"]

    @staticmethod
    def stop_process(process):
        if process.poll() is None:  # None means still running
            process.terminate()
            # No good reason to wait, plus it interferes with
            # how stop button on the Mark 1 operates.
            # process.wait()
            return True
        else:
            return False

    # Handle: "Delete recording"
    @intent_handler(IntentBuilder('').require('Delete').require('Recording'))
    def handle_delete(self, message):
        if not exists(self.settings["file_path"]):
            self.speak_dialog('audio.record.no.recording')
        else:
            try:
                os.remove(self.settings["file_path"])
                self.speak_dialog('audio.record.removed')
            except:
                pass

    # Standard Stop handler
    def stop(self):
        if self.record_process:
            self.end_recording()
            return True
        if self.play_process:
            self.end_playback()
            return True
        return False

    # Show a countdown using the eyes
    def render_countdown(self, r_fore, g_fore, b_fore):
        display_owner = self.enclosure.display_manager.get_active()
        if display_owner == "":
            # Initialization, first time we take ownership
            self.enclosure.mouth_reset()  # clear any leftover bits
            self.enclosure.eyes_color(r_fore, g_fore, b_fore)  # foreground
            self.last_index = 24

        if display_owner == "AudioRecordSkill":
            remaining_pct = self.remaining_time() / self.settings["duration"]
            fill_to_index = int(24 * remaining_pct)
            while self.last_index > fill_to_index:
                if self.last_index < 24 and self.last_index > -1:
                    # fill background with gray
                    self.enclosure.eyes_setpixel(self.last_index, 64, 64, 64)
                self.last_index -= 1

    ######################################################################
    # Recording

    @intent_file_handler('StartRecording.intent')
    def handle_record(self, message):
        utterance = message.data.get('utterance')

        # Calculate how long to record
        self.start_time = now_local()
        stop_time, _ = extract_datetime(utterance, lang=self.lang)
        self.settings["duration"] = (stop_time -
                                     self.start_time).total_seconds()
        if self.settings["duration"] <= 0:
            self.settings["duration"] = 60  # default recording duration

        # Throw away any previous recording
        try:
            os.remove(self.settings["file_path"])
        except:
            pass

        if self.has_free_disk_space():
            record_for = nice_duration(self, self.settings["duration"],
                                       lang=self.lang)
            self.speak_dialog('audio.record.start.duration',
                              {'duration': record_for})

            # Initiate recording
            wait_while_speaking()
            self.start_time = now_local()   # recalc after speaking completes
            self.record_process = record(self.settings["file_path"],
                                         int(self.settings["duration"]),
                                         self.settings["rate"],
                                         self.settings["channels"])
            self.enclosure.eyes_color(255, 0, 0)  # set color red
            self.last_index = 24
            self.schedule_repeating_event(self.recording_feedback, None, 1,
                                          name='RecordingFeedback')
        else:
            self.speak_dialog("audio.record.disk.full")

    def recording_feedback(self, message):
        if not self.record_process:
            self.end_recording()
            return

        # Show recording countdown
        self.render_countdown(255, 0, 0)

        # Verify there is still adequate disk space to continue recording
        if self.record_process.poll() is None:
            if not self.has_free_disk_space():
                # Out of space
                self.end_recording()
                self.speak_dialog("audio.record.disk.full")
        else:
            # Recording ended for some reason
            self.end_recording()

    def end_recording(self):
        self.cancel_scheduled_event('RecordingFeedback')

        if self.record_process:
            # Stop recording
            self.stop_process(self.record_process)
            self.record_process = None
            # Calc actual recording duration
            self.settings["duration"] = (now_local() -
                                         self.start_time).total_seconds()

        # Reset eyes
        self.enclosure.eyes_color(34, 167, 240)  # Mycroft blue
        self.bus.emit(Message('mycroft.eyes.default'))

    ######################################################################
    # Playback

    @intent_file_handler('PlayRecording.intent')
    def handle_play(self, message):
        if exists(self.settings["file_path"]):
            # Initialize for playback
            self.start_time = now_local()

            # Playback the recording, with visual countdown
            self.play_process = play_wav(self.settings["file_path"])
            self.enclosure.eyes_color(64, 255, 64)  # set color greenish
            self.last_index = 24
            self.schedule_repeating_event(self.playback_feedback, None, 1,
                                          name='PlaybackFeedback')
        else:
            self.speak_dialog('audio.record.no.recording')

    def playback_feedback(self, message):
        if not self.play_process or self.play_process.poll() is not None:
            self.end_playback()
            return

        if self.settings["duration"] > -1:
            # Show playback countdown
            self.render_countdown(64, 255, 64)   # greenish color
        else:
            # unknown duration, can't display countdown
            pass

    def end_playback(self):
        self.cancel_scheduled_event('PlaybackFeedback')
        if self.play_process:
            self.stop_process(self.play_process)
            self.play_process = None

        # Reset eyes
        self.enclosure.eyes_color(34, 167, 240)  # Mycroft blue
        self.bus.emit(Message('mycroft.eyes.default'))


def create_skill():
    return AudioRecordSkill()


##########################################################################
# TODO: Move to mycroft.util.format
from mycroft.util.format import pronounce_number


def nice_duration(self, duration, lang="en-us", speech=True):
    """ Convert duration in seconds to a nice spoken timespan

    Examples:
       duration = 60  ->  "1:00" or "one minute"
       duration = 163  ->  "2:43" or "two minutes forty three seconds"

    Args:
        duration: time, in seconds
        speech (bool): format for speech (True) or display (False)
    Returns:
        str: timespan as a string
    """

    # Do traditional rounding: 2.5->3, 3.5->4, plus this
    # helps in a few cases of where calculations generate
    # times like 2:59:59.9 instead of 3:00.
    duration += 0.5

    days = int(duration // 86400)
    hours = int(duration // 3600 % 24)
    minutes = int(duration // 60 % 60)
    seconds = int(duration % 60)

    if speech:
        out = ""
        if days > 0:
            out += pronounce_number(days, lang) + " "
            if days == 1:
                out += self.translate("day")
            else:
                out += self.translate("days")
            out += " "
        if hours > 0:
            if out:
                out += " "
            out += pronounce_number(hours, lang) + " "
            if hours == 1:
                out += self.translate("hour")
            else:
                out += self.translate("hours")
        if minutes > 0:
            if out:
                out += " "
            out += pronounce_number(minutes, lang) + " "
            if minutes == 1:
                out += self.translate("minute")
            else:
                out += self.translate("minutes")
        if seconds > 0:
            if out:
                out += " "
            out += pronounce_number(seconds, lang) + " "
            if seconds == 1:
                out += self.translate("second")
            else:
                out += self.translate("seconds")
    else:
        # M:SS, MM:SS, H:MM:SS, Dd H:MM:SS format
        out = ""
        if days > 0:
            out = str(days) + "d "
        if hours > 0 or days > 0:
            out += str(hours) + ":"
        if minutes < 10 and (hours > 0 or days > 0):
            out += "0"
        out += str(minutes)+":"
        if seconds < 10:
            out += "0"
        out += str(seconds)

    return out
