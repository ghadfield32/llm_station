"""The seven core adapter capability probes."""
from .attachments import probe_attachments
from .interrupt import probe_interrupt
from .model_switch import probe_model_switch
from .resume import probe_resume
from .steering import probe_steering
from .streaming import probe_streaming
from .write_mode_wall import probe_write_mode_wall

PROBES = (
    probe_streaming,
    probe_resume,
    probe_write_mode_wall,
    probe_attachments,
    probe_model_switch,
    probe_interrupt,
    probe_steering,
)
