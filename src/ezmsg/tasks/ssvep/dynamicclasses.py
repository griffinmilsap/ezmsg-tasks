import math
import param
import typing
import asyncio

import panel as pn

class DynamicClasses(pn.Column):
    intermod: bool

    classes: pn.Column
    add_btn: pn.widgets.Button
    common_base_switch: typing.Optional[pn.widgets.Switch]
    common_base_input: typing.Optional[pn.widgets.FloatInput]
    common_base_unit: typing.Optional[pn.Row]

    nc: int = 0

    class ClassEntry(pn.Column):

        intermod: bool
        common_base: typing.Optional[bool]
        del_btn: pn.widgets.Button
        class_freq: pn.widgets.FloatInput
        base_freq: typing.Optional[pn.widgets.FloatInput]


        def __init__(self,
                     class_no: int,
                     intermod: bool,
                     del_callback: typing.Callable[["DynamicClasses.ClassEntry"], None],
                     class_change_callback: typing.Callable[[param.parameterized.Event], None],
                     common_base: bool = None,
                     *args,
                     **kwargs) -> None:
            super().__init__(*args, **kwargs)


            self.intermod = intermod
            self.common_base = common_base

            self.del_btn = pn.widgets.Button(name='X', width=30)
            self.del_btn.on_click(lambda _: del_callback(self))

            class_format = dict(value=0, start=0, end=60, format='0.00', sizing_mode='stretch_width')

            self.class_freq = pn.widgets.FloatInput(
                name = f'Class {class_no} (Hz)',
                **class_format
            )

            self.class_freq.param.watch(class_change_callback, 'value')
            
            if intermod and not self.common_base:
                self.base_freq = pn.widgets.FloatInput(
                    name = f'Base {class_no} (Hz)',
                    **class_format
                )
                self.extend([
                    pn.Row(self.del_btn, self.base_freq, self.class_freq),
                    pn.layout.Divider()
                ])
            else:
                self.extend([
                    pn.Row(self.del_btn, self.class_freq),
                    pn.layout.Divider()
                ])
        
        @property
        def setting(self) -> typing.Tuple[typing.Optional[str], typing.Tuple[float, float]]:
            class_name: str = self.class_freq.name
            class_freq: float = self.class_freq.value
            base_freq: typing.Optional[float]

            if self.intermod and not self.common_base:
                base_freq = self.base_freq.value
                return (class_name, (class_freq, base_freq))
            else:
                return (class_name, (class_freq, 0))

    def __init__(self, 
                 intermod: bool, 
                 *args, 
                 **kwargs) -> None:
        super().__init__(*args, **kwargs)

        async def class_change_callback(event):
            print(event)
            print(type(event))
            val = event.new
            
            if(val != 0):
                frac, _ = math.modf((1/val)*1000)
                if(frac != 0):
                    # throw toast to notify the user
                    event.cls.value = 1/(round((1/val)*1000)/1000)
                    alrt = pn.pane.Alert('## Warning\nInvalid input value: '+str(val)+'\nChanging '+event.cls.name+' frequency to closest valid value of '+f'{event.cls.value:.02f}',
                                alert_type='warning')
                    val = 1/(round((1/val)*1000)/1000)
                    self.insert(0, alrt)
                    await asyncio.sleep(3)
                    self.remove(alrt)
                
                if('Base' not in event.obj.name):
                    for c in self.classes.objects:
                        if(c[0][1].name != event.obj.name and c[0][1].value == val):
                            event.cls.value = 0
                            alrt = pn.pane.Alert('## Error\nFrequency input already in use, please select a different frequency',
                                    alert_type='danger')
                            self.insert(0, alrt)
                            await asyncio.sleep(3)
                            self.remove(alrt)

        self.intermod = intermod

        self.classes = pn.Column()

        def add_row() -> None:

            if(self.intermod):
                entry = DynamicClasses.ClassEntry(
                    class_no=len(self.classes)+1,
                    intermod=self.intermod,
                    common_base=self.common_base_switch.value,
                    del_callback=self.classes.remove,
                    class_change_callback=class_change_callback
                )
            else:
                entry = DynamicClasses.ClassEntry(
                    class_no=len(self.classes)+1,
                    intermod=self.intermod,
                    del_callback=self.classes.remove,
                    class_change_callback=class_change_callback
                )
            self.classes.append(entry)

        if(self.intermod):
            print('in self.intermod')
            self.common_base_switch = pn.widgets.Switch(name='Common Base Frequency',
                                                value=True, align=('center'))

            class_format = dict(value=0, start=0, end=60, format='0.00', sizing_mode='stretch_width')
            self.common_base_input = pn.widgets.FloatInput(name='Base Frequency (Hz)', **class_format)
            self.common_base_input.param.watch(class_change_callback, 'value')

            self.common_base_unit = pn.Row(pn.pane.Markdown('Common Base Frequency'), self.common_base_switch)

            self.insert(0, self.common_base_unit)
            self.insert(1, self.common_base_input)

            async def common_base_freq_callback(event):
                self.remove(self.classes)
                self.classes = pn.Column()
                self.insert(-1, self.classes)
                if event.new == True:
                    self.common_base_input.visible = True
                else:
                    self.common_base_input.visible = False
                add_row()
            self.common_base_switch.param.watch(common_base_freq_callback, 'value')
        
        add_row()

        self.add_btn = pn.widgets.Button(
            name = 'Add Class',
            sizing_mode = 'stretch_width'
        )

        self.add_btn.on_click(lambda _: add_row())

        self.extend([
            self.classes,
            self.add_btn

        ])
    
    @property
    def setting(self) -> typing.Dict[typing.Optional[str], typing.Tuple[float, float]]:
        rows: typing.List[DynamicClasses.ClassEntry] = self.classes.objects
        ret = {}
        for row in rows:
            if(self.intermod and self.common_base_switch.value):
                ret[row.setting[0]] = (row.setting[1][0], self.common_base_input.value)
            else:
                ret[row.setting[0]] = row.setting[1]
        return ret
    
    @property
    def numClasses(self) -> int:
        return len(self.classes)
