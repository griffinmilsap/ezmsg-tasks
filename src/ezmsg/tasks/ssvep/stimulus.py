import param

from panel.reactive import ReactiveHTML

class CanvasStimulus(ReactiveHTML):

    border = param.Integer(default = 0)
    presented = param.Boolean(default = True)

    _template = """
    <canvas 
        id="stimulus_el"
        width="${model.width}"
        height="${model.height}"
        style="border: ${border}px solid black;"
        >
    </canvas>
    """

class SSVEPStimulus(CanvasStimulus):

    period_ms = param.Integer(default = 120)
    angular_freq = param.Number(default = 40.0)
    radial_freq = param.Number(default = 10.0)
    radial_exp = param.Number(default = 0.5)

    _scripts = {
        "render": """
            state.ctx = stimulus_el.getContext("2d");
            state.interval_id = null;
            state.period = -1;
        """,

        "after_layout": """
            self.design_stimulus();
            self.reschedule();
        """,

        "remove": """
            self.clear_interval()
        """,

        "clear_interval": """
            if(state.interval_id) {
                window.clearInterval(state.interval_id);
            }
        """,

        "reschedule": """
            self.clear_interval();
            state.period = data.period_ms;
            state.interval_id = window.setInterval(self.draw, state.period);
        """,

        "design_stimulus": """
            state.width = stimulus_el.width;
            state.height = stimulus_el.height;
            state.ctx.clearRect(0, 0, state.width, state.height);

            // Assumption: state.id_a.data and state.id_b.data have the same length
            state.id_a = state.ctx.getImageData(0, 0, state.width, state.height);
            state.id_b = state.ctx.getImageData(0, 0, state.width, state.height);

            cx = state.width / 2.0;
            cy = state.height / 2.0;

            for(let offset = 0; offset < state.id_a.data.length; offset += 4) {
                pixel_idx = Math.floor(offset / 4);
                x = pixel_idx % state.width;
                y = Math.floor(pixel_idx / state.width);

                xv = (x - cx) / cx;
                yv = (y - cy) / cy;

                dist = Math.pow(Math.sqrt((xv * xv) + (yv * yv)), data.radial_exp);
                angle = Math.atan2(yv, xv);
                value = Math.sin(2 * Math.PI * (data.radial_freq / 2.0) * dist);
                value *= Math.cos(angle * data.angular_freq / 2.0);

                if(dist <= 1.0){
                    state.id_a.data[offset + 0] = value <= 0 ? 0 : 255;
                    state.id_b.data[offset + 0] = value <= 0 ? 255 : 0;
                    state.id_a.data[offset + 1] = value <= 0 ? 0 : 255;
                    state.id_b.data[offset + 1] = value <= 0 ? 255 : 0;
                    state.id_a.data[offset + 2] = value <= 0 ? 0 : 255;
                    state.id_b.data[offset + 2] = value <= 0 ? 255 : 0;
                    state.id_a.data[offset + 3] = 255;
                    state.id_b.data[offset + 3] = 255;
                }
            }

            state.reverse = false
        """,

        "draw": """
            state.ctx.clearRect(0, 0, state.width, state.height);
            if(data.presented) {
                state.ctx.putImageData(state.reverse ? state.id_a : state.id_b, 0, 0);
            }
            state.reverse = !state.reverse
        """
    }

class VisualMotionStimulus(CanvasStimulus):

    # For compatibility with SSVEPStimulus where period_ms represents single reversal period
    # this actually refers to the half-rotation period
    period_ms = param.Integer(default = 120)

    _scripts = {
        "render": """
            state.ctx = stimulus_el.getContext("2d");
            state.requestId = window.requestAnimationFrame(self.draw)
        """,

        "draw": """
            state.ctx.clearRect(0, 0, stimulus_el.width, stimulus_el.height);
            if(data.presented) {
                cx = Math.floor(stimulus_el.width / 2);
                cy = Math.floor(stimulus_el.height / 2);

                const date = new Date();
                t = date.getTime() / 1000;
                f = 1000 / (2.0 * data.period_ms); // period corresponds to a half-rotation
                w = 2 * Math.PI * f * t;
                v = Math.sin(w);
                radius_x = Math.floor(cx * Math.abs(v)); // pixels
                radius_y = cy; // pixels
                rotation = 0; // pixels
                start_angle = 0; // radians
                end_angle = 2 * Math.PI; // radians

                state.ctx.beginPath()
                lum = Math.floor(((v + 1.0) / 2.0) * 255);
                state.ctx.fillStyle = `rgb(${lum}, ${lum}, ${lum})`;
                state.ctx.ellipse(cx, cy, radius_x, radius_y, rotation, start_angle, end_angle)
                state.ctx.fill()
            }
            state.requestId = window.requestAnimationFrame(self.draw)
        """,

        "remove": """
            window.cancelAnimationFrame(state.requestId)
        """,
    }

class IntermodulationSSVEP(CanvasStimulus):

    # For compatibility with SSVEPStimulus where period_ms represents single reversal period
    # this actually refers to the half-rotation period
    period_ms = param.Integer(default = 70)
    period_ms_2 = param.Integer(default = 90)

    _scripts = {
        "render": """
            state.ctx = stimulus_el.getContext("2d");
            state.requestId = window.requestAnimationFrame(self.draw)
        """,

        "draw": """
            state.ctx.clearRect(0, 0, stimulus_el.width, stimulus_el.height);
            if(data.presented) {
                cx = Math.floor(stimulus_el.width / 2);
                cy = Math.floor(stimulus_el.height / 2);

                const date = new Date();
                t = date.getTime() / 1000;
                w1 = 2 * Math.PI * 1000 / (2.0 * data.period_ms) * t;
                w2 = 2 * Math.PI * 1000 / (2.0 * data.period_ms_2) * t;
                v = (Math.cos(w1) + Math.cos(w2))/2;
                rotation = 0; // pixels
                start_angle = 0; // radians
                end_angle = 2 * Math.PI; // radians

                state.ctx.beginPath()
                lum = Math.floor(((v + 1.0) / 2.0) * 255);
                state.ctx.fillStyle = `rgb(${lum}, ${lum}, ${lum})`;
                state.ctx.ellipse(cx, cy, cx, cy, rotation, start_angle, end_angle)
                state.ctx.fill()
            }
            state.requestId = window.requestAnimationFrame(self.draw)
        """,

        "remove": """
            window.cancelAnimationFrame(state.requestId)
        """,
    }