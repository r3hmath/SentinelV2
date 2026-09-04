import cv2


class CameraStream:

    def __init__(
        self,
        source: str | int,
    ):

        self.source = source
        self.capture = None

    def open(self):

        self.capture = cv2.VideoCapture(
            self.source
        )

        if not self.capture.isOpened():

            raise RuntimeError(
                f"Unable to open camera source: "
                f"{self.source}"
            )

    def read(self):

        if self.capture is None:
            raise RuntimeError(
                "Camera is not opened"
            )

        return self.capture.read()

    def release(self):

        if self.capture:

            self.capture.release()

            self.capture = None