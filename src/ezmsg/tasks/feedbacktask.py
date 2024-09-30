import typing
import asyncio


import ezmsg.core as ez
import panel as pn

from ezmsg.sigproc.sampler import SampleTriggerMessage

from .task import (
    Task,
    TaskComplete,
    TaskImplementation,
    TaskImplementationState,
)
    

class FeedbackTaskImplementationState(TaskImplementationState):
    stimulus: pn.widgets.StaticText
    task_area: pn.layout.Card

    run_duration: pn.widgets.FloatInput
    task_controls: pn.layout.WidgetBox

    input_class: asyncio.Queue[typing.Optional[str]]

class FeedbackTaskImplementation(TaskImplementation):
    STATE = FeedbackTaskImplementationState

    INPUT_CLASS = ez.InputStream(typing.Optional[str])
    
    @property
    def slug(self) -> str:
        """ Short-name used to identify recorded files """
        return 'FEEDBACK'
    
    @property
    def title(self) -> str:
        """ Title of task used in header of page """
        return 'Feedback Task'
    
    async def initialize(self) -> None:
        await super().initialize()
        self.STATE.stimulus = pn.widgets.StaticText(
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
                    self.STATE.stimulus,
                    pn.layout.HSpacer()
                ),
                pn.layout.VSpacer(),
                min_height = 600,
            ),
            styles = {'background': 'lightgray'},
            hide_header = True,
            sizing_mode = 'stretch_both'
        )


        self.STATE.run_duration = pn.widgets.FloatInput(
            name = 'Run Duration (sec) -- 0 = Run Forever', 
            start = 0, 
            sizing_mode = 'stretch_width'
        )

        @pn.depends(self.STATE.run_duration, watch = True)
        def update_run_calc(run_duration: float):
            if run_duration != 0:
                self.STATE.run_info.value = f'Duration: {run_duration} sec'
            else:
                self.STATE.run_info.value = f'Duration: Until Stopped'
        
        self.STATE.run_duration.value = 30

        self.STATE.task_controls = pn.WidgetBox(
            self.STATE.run_duration,
            sizing_mode = 'stretch_width'
        )

        self.STATE.input_class = asyncio.Queue()

        self.STATE.progress.max = 100
        self.STATE.progress.value = 0
    
    @ez.subscriber(INPUT_CLASS)
    async def on_class_input(self, msg: typing.Optional[str]) -> None:
        self.STATE.input_class.put_nowait(msg)
        if msg: 
            self.STATE.stimulus.value = msg
        else:
            self.STATE.stimulus.value = ''

    async def task_implementation(self) -> typing.AsyncIterator[typing.Optional[SampleTriggerMessage]]:

        self.STATE.task_controls.disabled = True

        try:
            # Grab all widget values so they can't be changed during run
            run_duration: float = self.STATE.run_duration.value # type: ignore

            self.STATE.status.value = 'Running...'
            self.STATE.progress.bar_color = 'primary'
            self.STATE.progress.disabled = False

            if run_duration == 0:
                self.STATE.progress.value = self.STATE.progress.max
                self.STATE.progress.active = True

                while True:
                    await asyncio.sleep(0.1)
                    yield None
            
            else:
                self.STATE.progress.value = 0
                sleep_time = run_duration / self.STATE.progress.max
                for itr in range(self.STATE.progress.max):
                    # thrilling, I know ;)
                    await asyncio.sleep(sleep_time)
                    self.STATE.progress.value = itr + 1
                    yield None

                raise TaskComplete

        finally:
            self.STATE.progress.active = False
            self.STATE.task_controls.disabled = False
    
    def content(self) -> pn.viewable.Viewable:
        return self.STATE.task_area
    
    def sidebar(self) -> pn.viewable.Viewable:
        sidebar = super().sidebar()
        sidebar.extend([
            pn.Card(
                self.STATE.task_controls, 
                title = 'Feedback Task'
            )
        ])
        return sidebar


class FeedbackTask(Task):
    INPUT_CLASS = ez.InputStream(typing.Optional[str])

    TASK: FeedbackTaskImplementation = FeedbackTaskImplementation()

    def network(self) -> ez.NetworkDefinition:
        return list(super().network()) + [
            (self.INPUT_CLASS, self.TASK.INPUT_CLASS),
        ]