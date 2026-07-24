"""The five core adapter capability probes."""
from .attachments import probe_attachments
from .model_switch import probe_model_switch
from .resume import probe_resume
from .streaming import probe_streaming
from .write_mode_wall import probe_write_mode_wall

PROBES = (
    probe_streaming,
    probe_resume,
    probe_write_mode_wall,
    probe_attachments,
    probe_model_switch,
)
