import logging

import requests


logger = logging.getLogger(__name__)


class EventClient:

    def __init__(
        self,
        base_url: str,
    ):

        self.url = (
            f"{base_url.rstrip('/')}"
            "/api/events"
        )

        self.session = requests.Session()


    def send(self, event: dict) -> bool:

        try:

            response = self.session.post(

                self.url,

                json=event,

                timeout=3,
            )

            response.raise_for_status()

            return True

        except requests.RequestException as exc:

            logger.error(
                "Failed to send event: %s",
                exc,
            )

            return False


    def close(self):

        self.session.close()