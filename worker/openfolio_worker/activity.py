"""Track real conversation activity so the idle timer never cuts off an answer."""
import time
from pipecat.frames.frames import (
    BotStartedSpeakingFrame, BotStoppedSpeakingFrame, BotSpeakingFrame,
    LLMFullResponseStartFrame, LLMFullResponseEndFrame, LLMTextFrame,
    TranscriptionFrame, InterimTranscriptionFrame, LLMMessagesAppendFrame,
    UserStartedSpeakingFrame, UserStoppedSpeakingFrame, UserSpeakingFrame,
    InterruptionFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed


class ConversationActivity(BaseObserver):
    def __init__(self, clock=time.monotonic):
        super().__init__(observe_every_push=False)
        self.clock = clock
        self.last_activity = clock()
        self.speaking = False
        self.generating = False
        self.user_speaking = False

    def record(self, frame):
        if isinstance(frame, BotStartedSpeakingFrame):
            self.speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self.speaking = False
        elif isinstance(frame, LLMFullResponseStartFrame):
            self.generating = True
        elif isinstance(frame, LLMFullResponseEndFrame):
            self.generating = False
        elif isinstance(frame, UserStartedSpeakingFrame):
            self.user_speaking = True
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self.user_speaking = False
        elif isinstance(frame, InterruptionFrame):
            self.speaking = self.generating = False
        elif not isinstance(frame, (BotSpeakingFrame, UserSpeakingFrame, LLMTextFrame,
                                   TranscriptionFrame, InterimTranscriptionFrame, LLMMessagesAppendFrame)):
            return
        self.last_activity = self.clock()

    def is_idle(self, seconds):
        return (not self.speaking and not self.generating and not self.user_speaking
                and self.clock() - self.last_activity >= seconds)

    async def on_push_frame(self, data: FramePushed):
        self.record(data.frame)
