# Ultralytics YOLO 🚀, AGPL-3.0 license

from copy import copy

from ultralytics.models import yolo
from ultralytics.nn.tasks import OrientationModel
from ultralytics.utils import DEFAULT_CFG, RANK
from ultralytics.utils.plotting import plot_images, plot_results


class OrientationTrainer(yolo.detect.DetectionTrainer):
    """
    A class extending the DetectionTrainer class for training based on an Orientation model.

    Example:
        ```python
        from ultralytics.models.yolo.orienty import OrientationTrainer

        args = dict(model='yolov8n-ori.pt', data='your custom data', epochs=3)
        trainer = OrientationTrainer(overrides=args)
        trainer.train()
        ```
    """

    def __init__(self, cfg=DEFAULT_CFG, overrides=None, _callbacks=None):
        """Initialize a OrientationTrainer object with given arguments."""
        if overrides is None:
            overrides = {}
        overrides["task"] = "orienty"
        super().__init__(cfg, overrides, _callbacks)

    def get_validator(self):
        """Return an instance of OrientationValidator for validation of YOLO model."""
        self.loss_names = "box_loss", "deg_loss", "cls_loss", "dfl_loss"
        return yolo.orienty.OrientationValidator(self.test_loader, save_dir=self.save_dir, args=copy(self.args))

    def get_model(self, cfg=None, weights=None, verbose=True):
        """Return a YOLO orientation model."""
        model = OrientationModel(cfg, nc=self.data["nc"], verbose=verbose and RANK == -1)
        if weights:
            model.load(weights)
        return model

    def plot_training_samples(self, batch, ni):
        """Creates a plot of training sample images with labels and box coordinates."""
        plot_images(
            batch["img"],
            batch["batch_idx"],
            batch["cls"].squeeze(-1),
            batch["bboxes"],
            degs=batch["degs"],
            paths=batch["im_file"],
            fname=self.save_dir / f"train_batch{ni}.jpg",
            on_plot=self.on_plot,
        )

    def plot_metrics(self):
        """Plots training/val metrics."""
        plot_results(file=self.csv, orienty=True, on_plot=self.on_plot)  # save results.png
