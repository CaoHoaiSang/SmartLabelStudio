"""Small pack helper: a hidden widget cannot be used as a Tk `before` anchor."""
import logging


logger = logging.getLogger(__name__)


def pack_before(widget, anchor=None, **options):
    if anchor is not None and anchor.master == widget.master and anchor.winfo_manager() == "pack":
        options["before"] = anchor
    elif anchor is not None:
        logger.warning("Layout anchor is not packed in the same container; appending %s", widget)
    widget.pack(**options)
