import typing

import panel as pn
from param.parameterized import Event

class DynamicClasses(pn.Column):

    classes: pn.Column
    add_btn: pn.widgets.Button

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.classes = pn.Column()

        def add_row() -> None:
            self.classes.append(
                DynamicClasses.ClassEntry(
                    del_callback = self.classes.remove,
                )
            )

        self.add_btn = pn.widgets.Button(
            name = 'Add Class',
            sizing_mode = 'stretch_width'
        )

        self.add_btn.on_click(lambda _: add_row())

        add_row()

        self.extend([
            self.classes,
            self.add_btn
        ])
    
    @property
    def setting(self) -> typing.List[int]:
        rows: typing.List[DynamicClasses.ClassEntry] = self.classes.objects # type: ignore
        return [row.setting for row in rows]
    
    @property
    def numClasses(self) -> int:
        return len(self.classes)


    class ClassEntry(pn.Column):

        del_callback_type = typing.Callable[["DynamicClasses.ClassEntry"], None]

        del_btn: pn.widgets.Button
        period: pn.widgets.IntInput
        freq: pn.widgets.StaticText

        def __init__(self, del_callback: del_callback_type, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)

            self.del_btn = pn.widgets.Button(name = 'X', width = 30, align = ('start', 'end'))
            self.del_btn.on_click(lambda _: del_callback(self))

            self.period = pn.widgets.IntInput(
                name = f'Period (ms)', 
                value = 80, 
                start = 10, 
                step = 1, 
                sizing_mode = 'stretch_width'
            )

            self.freq = pn.widgets.StaticText(name = 'Rate')

            def update_freq(e: Event) -> None:
                self.freq.value = f'{1000/e.new:.02f} Hz'

            self.period.param.watch(update_freq, 'value')
            self.period.value = 100 # Just to kick the update
            
            self.extend([
                pn.Row(self.del_btn, self.period, self.freq),
                pn.layout.Divider()
            ])
        
        @property
        def setting(self) -> int:
            return self.period.value # type: ignore
            