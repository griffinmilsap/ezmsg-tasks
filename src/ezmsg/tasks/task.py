import asyncio
import typing
import datetime

from pathlib import Path

import ezmsg.core as ez
import panel as pn

from ezmsg.panel.tabbedapp import Tab
from ezmsg.sigproc.sampler import Sampler, SamplerSettings, SampleMessage, SampleTriggerMessage
from ezmsg.util.messages.axisarray import AxisArray
from ezmsg.util.messagelogger import MessageLogger

from param.parameterized import Event


class TaskException(Exception):
    ...

class TaskEndedEarly(TaskException):
    ...

class TaskComplete(TaskException):
    ...


class TaskSettings(ez.Settings):
    data_dir: Path
    buffer_dur: float = 10.0


class TaskImplementationState(ez.State):
    progress: pn.indicators.Progress
    status: pn.widgets.StaticText
    run_info: pn.widgets.StaticText
    run_button: pn.widgets.Button
    run_event: asyncio.Event
    status_card: pn.layout.Card

    recording_controls: pn.layout.WidgetBox
    recording_subdir: pn.widgets.TextInput
    recording_fname: pn.widgets.StaticText
    n_trials: pn.indicators.Number
    recording_card: pn.layout.Card

    recording_path: typing.Optional[Path]
    recording_started: asyncio.Event
    recording_stopped: asyncio.Event

    trigger_queue: asyncio.Queue[SampleTriggerMessage]


class TaskImplementation(ez.Unit, Tab):

    # NOTE: For compatibility with TaskDirectory, 
    # Task implementations should NOT have derived settings
    # This should be a reasonable ask because we will have UI for such things

    SETTINGS = TaskSettings
    STATE: TaskImplementationState

    OUTPUT_TRIGGER = ez.OutputStream(SampleTriggerMessage)

    # I dislike this interface to MessageLogger.
    OUTPUT_LOGSTART = ez.OutputStream(Path)
    INPUT_LOGSTARTED = ez.InputStream(Path)
    INPUT_MESSAGELOGGED = ez.InputStream(SampleMessage)
    OUTPUT_LOGSTOP = ez.OutputStream(Path)
    INPUT_LOGSTOPPED = ez.InputStream(Path)
    
    @property
    def slug(self) -> str:
        """ Shortname used to identify recorded files """
        return 'TASK'

    @property
    def title(self) -> str:
        """ Full name of Task that appears in UI """
        return 'Task Implementation'
    
    async def initialize(self) -> None:
        
        sw = dict(sizing_mode = 'stretch_width')

        self.STATE.progress = pn.indicators.Progress(value = 1, max = 1, bar_color = 'success', **sw)
        self.STATE.status = pn.widgets.StaticText(name = 'Status', value = '', **sw)
        self.STATE.run_info = pn.widgets.StaticText(name = 'Run Info', **sw)
        self.STATE.run_button = pn.widgets.Button(name = 'Start Run', button_type = 'primary', **sw)
        self.STATE.run_event = asyncio.Event()

        async def on_run(_: Event) -> None:
            if self.STATE.run_event.is_set():
                self.STATE.run_button.name = 'Stopping...'
                self.STATE.run_button.disabled = True
                self.STATE.run_event.clear()
            else:
                self.STATE.run_button.name = 'Starting...'
                self.STATE.run_button.disabled = True
                self.STATE.run_event.set()
        
        self.STATE.run_button.on_click(on_run)

        self.STATE.status_card = pn.Card(
            self.STATE.status,
            self.STATE.progress,
            self.STATE.run_info,
            self.STATE.run_button,
            title = 'Status and Control',
        )

        self.STATE.recording_subdir = pn.widgets.TextInput(
            name = 'Recording Directory', 
            placeholder = 'Subdirectory name...',
            **sw
        )

        self.STATE.recording_path = None
        self.STATE.recording_fname = pn.widgets.StaticText(name = 'File', value = '', **sw)
        self.STATE.n_trials = pn.widgets.Number(value = 0, format = 'Recorded {value} Trials', font_size = '10pt', **sw)

        self.STATE.recording_controls = pn.layout.WidgetBox(
            self.STATE.recording_subdir,
            self.STATE.recording_fname,
            self.STATE.n_trials,
            **sw
        )

        self.STATE.recording_card = pn.layout.Card(
            self.STATE.recording_controls,
            title = 'Recording',
            **sw
        )
    
        self.STATE.trigger_queue = asyncio.Queue()
        self.STATE.recording_started = asyncio.Event()
        self.STATE.recording_stopped = asyncio.Event()

    @ez.publisher(OUTPUT_TRIGGER)
    async def pub_triggers(self) -> typing.AsyncGenerator:
        while True:
            trig = await self.STATE.trigger_queue.get()
            yield self.OUTPUT_TRIGGER, trig

    @ez.subscriber(INPUT_LOGSTARTED)
    async def on_log_started(self, msg: Path) -> None:
        ez.logger.debug(f'Log Started: {msg=}')
        if msg == self.STATE.recording_path:
            self.STATE.recording_started.set()

    @ez.subscriber(INPUT_LOGSTOPPED)
    async def on_log_stopped(self, msg: Path) -> None:
        ez.logger.debug(f'Log Stopped: {msg=}')
        if msg == self.STATE.recording_path:
            self.STATE.recording_stopped.set()
    
    @ez.publisher(OUTPUT_LOGSTART)
    @ez.publisher(OUTPUT_LOGSTOP)    
    async def run_task(self) -> typing.AsyncGenerator:
            
        while True:
            self.STATE.recording_path = None
            self.STATE.progress.disabled = True
            self.STATE.status.value = 'Idle'
            await self.STATE.run_event.wait()

            # There seems to be a race condition bug in Panel. disabling the button then
            # re-enabling it rapidly seems to cause a desynchronization between
            # the browser and the panel server which requires a refresh in browser.
            await asyncio.sleep(0.1)

            self.STATE.recording_subdir.disabled = True
            self.STATE.run_button.name = 'Stop Run'
            self.STATE.run_button.disabled = False

            recording_subdir: typing.Optional[str] = self.STATE.recording_subdir.value # type: ignore

            style = {'color': 'green'}
            self.STATE.n_trials.value = 0
            if recording_subdir:
                timestr = datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
                fname = f'{"-".join([timestr, self.slug])}.txt'
                record_file = self.SETTINGS.data_dir / 'recordings' / recording_subdir / fname
                self.STATE.recording_fname.value = '/'.join(record_file.parts[-2:])
                if not record_file.parent.exists():
                    record_file.parent.mkdir(parents = True, exist_ok = True)

                self.STATE.recording_path = record_file
                self.STATE.recording_started.clear()
                ez.logger.info(f'Start Log: {self.STATE.recording_path=}')
                yield self.OUTPUT_LOGSTART, self.STATE.recording_path
                await self.STATE.recording_started.wait()

            else:
                style = {'color': 'red'}
                self.STATE.recording_fname.value = 'NOT RECORDING'
            self.STATE.recording_fname.styles = style

            try:
                async for trigger in self.task_implementation():
                    if isinstance(trigger, SampleTriggerMessage):
                        self.STATE.trigger_queue.put_nowait(trigger)
                    if not self.STATE.run_event.is_set():
                        raise TaskEndedEarly()

            except TaskEndedEarly:
                ez.logger.warning(f'{self.name} - Task ended early')
                self.STATE.progress.bar_color = 'warning'

            except TaskComplete:
                ez.logger.info(f'{self.name} - Task complete')
                self.STATE.progress.bar_color = 'success'

            finally:
                await asyncio.sleep(0.1) # Workaround for race condition in Panel - Griff
                self.STATE.run_event.clear()
                self.STATE.run_button.name = 'Start Run'
                self.STATE.run_button.disabled = False

                self.STATE.recording_fname.styles = {}
                self.STATE.recording_subdir.disabled = False

                if self.STATE.recording_path:
                    self.STATE.recording_stopped.clear()
                    yield self.OUTPUT_LOGSTOP, self.STATE.recording_path
                    await self.STATE.recording_stopped.wait()
                    self.STATE.recording_path = None

    async def task_implementation(self) -> typing.AsyncIterator[typing.Optional[SampleTriggerMessage]]:
        yield None

    @ez.subscriber(INPUT_MESSAGELOGGED)
    async def on_sample(self, _: SampleMessage) -> None:
        self.STATE.n_trials.value += 1 # type: ignore

    def content(self):
        return pn.layout.Card(
            '# Task Area', 
            sizing_mode = 'stretch_both'
        )

    def sidebar(self):
        return pn.Column(
            self.STATE.status_card,
            self.STATE.recording_card
        )
    
class Task(ez.Collection, Tab):

    SETTINGS = TaskSettings

    TASK: TaskImplementation
    SAMPLER = Sampler()
    LOGGER = MessageLogger()

    INPUT_TRIGGER = ez.InputStream(SampleTriggerMessage)
    OUTPUT_TRIGGER = ez.OutputStream(SampleTriggerMessage)
    INPUT_SIGNAL = ez.InputStream(AxisArray)
    OUTPUT_SAMPLE = ez.OutputStream(SampleMessage)

    def configure(self) -> None:
        self.TASK.apply_settings(self.SETTINGS)
        self.SAMPLER.apply_settings(
            SamplerSettings(
                buffer_dur = self.SETTINGS.buffer_dur + 1.0
            )
        )

    @property
    def title(self) -> str:
        return self.TASK.title
            
    def sidebar(self) -> pn.viewable.Viewable:
        return self.TASK.sidebar()
                
    def content(self) -> pn.viewable.Viewable:
        return self.TASK.content()
        
    def network(self) -> ez.NetworkDefinition:
        return (
            (self.INPUT_SIGNAL, self.SAMPLER.INPUT_SIGNAL),
            (self.INPUT_TRIGGER, self.SAMPLER.INPUT_TRIGGER),
            (self.TASK.OUTPUT_TRIGGER, self.SAMPLER.INPUT_TRIGGER),
            (self.TASK.OUTPUT_TRIGGER, self.OUTPUT_TRIGGER),
            (self.SAMPLER.OUTPUT_SAMPLE, self.OUTPUT_SAMPLE),

            # Again, I really dislike this interface
            # MessageLogger should have a generator interface that we 
            # can build message logging into other units
            # without this level of plumbing work.
            (self.TASK.OUTPUT_LOGSTART, self.LOGGER.INPUT_START),
            (self.LOGGER.OUTPUT_START, self.TASK.INPUT_LOGSTARTED),
            (self.SAMPLER.OUTPUT_SAMPLE, self.LOGGER.INPUT_MESSAGE),
            (self.LOGGER.OUTPUT_MESSAGE, self.TASK.INPUT_MESSAGELOGGED),
            (self.TASK.OUTPUT_LOGSTOP, self.LOGGER.INPUT_STOP),
            (self.LOGGER.OUTPUT_STOP, self.TASK.INPUT_LOGSTOPPED),
        )