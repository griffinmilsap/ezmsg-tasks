import typing
import asyncio
import datetime
import random
import wave
import tempfile

import ezmsg.core as ez
import panel as pn
import numpy as np

from ezmsg.sigproc.sampler import SampleTriggerMessage

from .task import (
    Task,
    TaskComplete,
    TaskImplementation,
    TaskImplementationState,
)

from dataclasses import dataclass, field

@dataclass(frozen = True)
class SSAEPStimulus:
    """ https://doi.org/10.1109/MetroInd4.0IoT51437.2021.9488530 """

    duration: float # sec
    fs: float = 41000 # Hz
    left_carrier: float = 450.0 # Hz
    left_modulation: float = 9.0 # Hz
    right_carrier: float = 650.0 # Hz
    right_modulation: float = 13.0 # Hz

    _file: tempfile._TemporaryFileWrapper = field(init = False)

    @property
    def filename(self) -> str:
        return self._file.name

    def __post_init__(self) -> None:

        n_samp = int(self.duration * self.fs)
        t = np.arange(n_samp) / self.fs
        freq = lambda f: np.cos(2.0 * np.pi * f * t)
        stimulus = np.dstack([
            freq(self.left_carrier) * freq(self.left_modulation),
            freq(self.right_carrier) * freq(self.right_modulation)
        ]) * np.iinfo(np.int16).max
        stereo_frames = stimulus.astype(np.int16).flatten()

        file = tempfile.NamedTemporaryFile(suffix = '.wav')
        with wave.open(file, 'wb') as wav_file:
            wav_file.setnchannels(2)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.fs)
            wav_file.writeframes(stereo_frames) # type: ignore

        # Working around frozen dataclass for file caching
        object.__setattr__(self, '_file', file)

@dataclass
class SSAEPSampleTriggerMessage(SampleTriggerMessage):
    freqs: typing.List[float] = field(default_factory=list)
    target: typing.Optional[int] = None


class SSAEPTaskImplementationState(TaskImplementationState):
    stimulus: SSAEPStimulus
    cue: pn.widgets.StaticText
    audio: pn.pane.Audio
    task_area: pn.layout.Card
    pre_run_duration: pn.widgets.FloatInput
    post_run_duration: pn.widgets.FloatInput
    trials_per_class: pn.widgets.IntInput
    trial_duration: pn.widgets.FloatInput
    intertrial_min_dur: pn.widgets.FloatInput
    intertrial_max_dur: pn.widgets.FloatInput
    task_controls: pn.layout.WidgetBox

    input_class: asyncio.Queue[typing.Optional[str]]
    output_class: asyncio.Queue[typing.Optional[str]]

class SSAEPTaskImplementation(TaskImplementation):
    STATE: SSAEPTaskImplementationState

    INPUT_CLASS = ez.InputStream(typing.Optional[str])
    OUTPUT_TARGET_CLASS = ez.OutputStream(typing.Optional[str])
    
    @property
    def slug(self) -> str:
        """ Short-name used to identify recorded files """
        return 'SSAEP'
    
    @property
    def title(self) -> str:
        """ Title of task used in header of page """
        return 'Steady State Auditory Evoked Potentials'
    
    async def initialize(self) -> None:
        await super().initialize()

        self.STATE.stimulus = SSAEPStimulus(duration = 10.0)
        self.STATE.audio = pn.pane.Audio(
            self.STATE.stimulus.filename, 
            name='SSAEP Stimulus', 
            autoplay = True, 
            muted = True,
            loop = True
        )

        self.STATE.cue = pn.widgets.StaticText(
            value = '...', 
            align = 'center',
            styles = {
                'color': 'black',
                'font-family': 'Arial, sans-serif',
                'font-size': '5em',
                'font-weight': 'bold'
            },
        )

        self.STATE.task_area = pn.Card(
            pn.Column(
                pn.layout.VSpacer(),
                pn.Row(
                    pn.layout.HSpacer(),
                    pn.Column(
                        self.STATE.cue,
                        self.STATE.audio,
                    ),
                    pn.layout.HSpacer()
                ),
                pn.layout.VSpacer(),
                min_height = 600,
            ),
            styles = {'background': 'lightgray'},
            hide_header = True,
            sizing_mode = 'stretch_both'
        )

        sw = dict(sizing_mode = 'stretch_width')

        self.STATE.trials_per_class = pn.widgets.IntInput(name = 'Trials per-class', value = 5, start = 1, **sw)
        self.STATE.pre_run_duration = pn.widgets.FloatInput(name = 'Pre-run (sec)', value = 3, start = 0, **sw)
        self.STATE.post_run_duration = pn.widgets.FloatInput(name = 'Post-run (sec)', value = 3, start = 0, **sw)

        self.STATE.trial_duration = pn.widgets.FloatInput(name = 'Trial dur. (sec)', value = 4.0, step = 0.1, start = 0.1, end = self.SETTINGS.buffer_dur, **sw)
        self.STATE.intertrial_min_dur = pn.widgets.FloatInput(name = 'ITI Min (sec)', value = 4.0, start = 0, step = 0.1, **sw)
        self.STATE.intertrial_max_dur = pn.widgets.FloatInput(name = 'ITI Max (sec)', value = 7.0, start = self.STATE.intertrial_min_dur.param.value, step = 0.1, **sw)

        @pn.depends(
                self.STATE.trials_per_class, 
                self.STATE.trial_duration,
                self.STATE.intertrial_min_dur,
                self.STATE.intertrial_max_dur,
                self.STATE.pre_run_duration,
                self.STATE.post_run_duration,
                watch = True )
        def update_run_calc(
            trials_per_class: int,
            trial_dur: float,
            iti_min: float,
            iti_max: float,
            pre_run: float,
            post_run: float
        ):
            n_trials = 2 * trials_per_class
            avg_iti = iti_min + (iti_max - iti_min) / 2
            run_len = (avg_iti + trial_dur) * n_trials
            run_len = pre_run + run_len + post_run
            run_dur = str(datetime.timedelta(seconds = run_len))
            self.STATE.run_info.value = f'{n_trials} LEFT and {n_trials} RIGHT trial(s), ~{run_dur}'

        # This is done here to kick the calculation for run_calc
        self.STATE.trials_per_class.param.update(value = 10)

        self.STATE.task_controls = pn.WidgetBox(
            pn.Row(
                self.STATE.trials_per_class,
                self.STATE.trial_duration,
            ),
            pn.Row(
                self.STATE.pre_run_duration,
                self.STATE.post_run_duration,
            ), 
            pn.Row(
                self.STATE.intertrial_min_dur, 
                self.STATE.intertrial_max_dur, 
            ),
            sizing_mode = 'stretch_both'
        )

        self.STATE.output_class = asyncio.Queue()
        self.STATE.input_class = asyncio.Queue()
    
    @ez.subscriber(INPUT_CLASS)
    async def on_class_input(self, msg: typing.Optional[str]) -> None:
        self.STATE.input_class.put_nowait(msg)

    @ez.publisher(OUTPUT_TARGET_CLASS)
    async def output_class(self) -> typing.AsyncGenerator:
        while True:
            out_class = await self.STATE.output_class.get()
            yield self.OUTPUT_TARGET_CLASS, out_class

    async def task_implementation(self) -> typing.AsyncIterator[typing.Optional[SampleTriggerMessage]]:

        self.STATE.task_controls.disabled = True

        try:
            # Grab all widget values so they can't be changed during run
            classes: typing.List[str] = ['⬅️ LEFT', 'RIGHT ➡️']
            freqs = [self.STATE.stimulus.left_modulation, self.STATE.stimulus.right_modulation]
            target_map = {c: idx for idx, c in enumerate(classes)}
            trials_per_class: int = self.STATE.trials_per_class.value # type: ignore
            trial_dur: float = self.STATE.trial_duration.value # type: ignore
            iti_min: float = self.STATE.intertrial_min_dur.value # type: ignore
            iti_max: float = self.STATE.intertrial_max_dur.value # type: ignore
            pre_run_duration: float = self.STATE.pre_run_duration.value # type: ignore
            post_run_duration: float = self.STATE.post_run_duration.value # type: ignore

            # Create trial order (blockwise randomized)
            trials: typing.List[str] = []
            for _ in range(trials_per_class):
                random.shuffle(classes)
                trials += classes

            self.STATE.progress.max = len(trials)
            self.STATE.progress.value = 0
            self.STATE.progress.bar_color = 'primary'
            self.STATE.progress.disabled = False

            self.STATE.status.value = 'Pre Run'
            await asyncio.sleep(pre_run_duration)

            for trial_idx, trial_class in enumerate(trials):

                trial_id = f'Trial {trial_idx + 1} / {len(trials)}'
                
                self.STATE.status.value = f'{trial_id}: Intertrial Interval'
                iti = random.uniform(iti_min, iti_max)
                self.STATE.cue.value = '...'
                self.STATE.audio.muted = True
                self.STATE.output_class.put_nowait(None)
                await asyncio.sleep(iti)

                self.STATE.status.value = f'{trial_id}: Action ({trial_class})'
                self.STATE.cue.value = trial_class
                self.STATE.audio.time = 0 # Reset the audio to 0 sec
                self.STATE.audio.muted = False
                self.STATE.output_class.put_nowait(trial_class)
                yield SSAEPSampleTriggerMessage(
                    period = (0.0, trial_dur), 
                    value = trial_class,
                    freqs = freqs,
                    target = target_map[trial_class]
                )
                await asyncio.sleep(trial_dur)
                self.STATE.progress.value = trial_idx + 1

            self.STATE.status.value = 'Post Run'
            self.STATE.cue.value = '...'
            self.STATE.audio.muted = True
            self.STATE.output_class.put_nowait(None)
            await asyncio.sleep(post_run_duration)

            raise TaskComplete

        finally:
            self.STATE.cue.value = '...'
            self.STATE.audio.muted = True
            self.STATE.task_controls.disabled = False
    
    def content(self) -> pn.viewable.Viewable:
        return self.STATE.task_area
    
    def sidebar(self) -> pn.viewable.Viewable:
        sidebar = super().sidebar()
        sidebar.extend([
            pn.Card(
                self.STATE.task_controls, 
                title = 'SSAEP Task'
            )
        ])
        return sidebar


class SSAEPTask(Task):
    INPUT_CLASS = ez.InputStream(typing.Optional[str])
    OUTPUT_TARGET_CLASS = ez.OutputStream(typing.Optional[str])

    TASK:SSAEPTaskImplementation = SSAEPTaskImplementation()

    def network(self) -> ez.NetworkDefinition:
        return list(super().network()) + [
            (self.INPUT_CLASS, self.TASK.INPUT_CLASS),
            (self.TASK.OUTPUT_TARGET_CLASS, self.OUTPUT_TARGET_CLASS)
        ]
    