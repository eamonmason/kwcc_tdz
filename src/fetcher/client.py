"""ZwiftPower HTTP client with authentication."""

import logging
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from src.fetcher.exceptions import (
    ZwiftPowerAuthError,
    ZwiftPowerConnectionError,
    ZwiftPowerRateLimitError,
)

logger = logging.getLogger(__name__)

ZWIFTPOWER_BASE_URL = "https://zwiftpower.com"
OAUTH_LOGIN_URL = (
    "https://zwiftpower.com/ucp.php?mode=login&login=external&oauth_service=oauthzpsso"
)
DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3
RETRY_DELAY = 5.0


class ZwiftPowerClient:
    """HTTP client for ZwiftPower with authentication support."""

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        """
        Initialize ZwiftPower client.

        Args:
            username: ZwiftPower/Zwift username
            password: ZwiftPower/Zwift password
            timeout: Request timeout in seconds
        """
        self.username = username
        self.password = password
        self.timeout = timeout
        self._client: httpx.Client | None = None
        self._authenticated = False

    def __enter__(self) -> "ZwiftPowerClient":
        """Context manager entry."""
        self._client = httpx.Client(
            base_url=ZWIFTPOWER_BASE_URL,
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        if self._client:
            self._client.close()
            self._client = None
        self._authenticated = False

    @property
    def client(self) -> httpx.Client:
        """Get the HTTP client, raising if not initialized."""
        if self._client is None:
            raise RuntimeError("ZwiftPowerClient must be used as context manager")
        return self._client

    def authenticate(self) -> bool:
        """
        Authenticate with ZwiftPower using Zwift OAuth SSO.

        Returns:
            True if authentication successful

        Raises:
            ZwiftPowerAuthError: If authentication fails
        """
        if not self.username or not self.password:
            logger.warning("No credentials provided, continuing without auth")
            return False

        logger.info("Authenticating with ZwiftPower via Zwift OAuth...")

        try:
            # Step 1: Start OAuth flow - redirects to Zwift login
            response = self.client.get(OAUTH_LOGIN_URL)

            if "zwift.com" not in str(response.url):
                logger.warning("OAuth did not redirect to Zwift login page")
                return False

            logger.debug(f"Redirected to Zwift login: {response.url}")

            # Step 2: Parse the Zwift login form
            soup = BeautifulSoup(response.text, "lxml")
            login_form = soup.find("form")

            if not login_form:
                logger.warning("No login form found on Zwift page")
                return False

            # Get form action and fields
            action = login_form.get("action", "")
            form_data = {}
            for inp in login_form.find_all("input"):
                name = inp.get("name")
                value = inp.get("value", "")
                if name:
                    form_data[name] = value

            # Fill in credentials
            if "username" in form_data:
                form_data["username"] = self.username
            elif "email" in form_data:
                form_data["email"] = self.username
            form_data["password"] = self.password

            # Determine submit URL
            if action.startswith("http"):
                submit_url = action
            elif action.startswith("/"):
                parsed = urlparse(str(response.url))
                submit_url = f"{parsed.scheme}://{parsed.netloc}{action}"
            else:
                submit_url = str(response.url)

            # Step 3: Submit login form
            logger.debug(f"Submitting login to: {submit_url}")
            login_response = self.client.post(
                submit_url,
                data=form_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            # Step 4: Check if we're back on ZwiftPower
            if "zwiftpower.com" not in str(login_response.url):
                logger.warning(
                    f"OAuth flow incomplete - landed at: {login_response.url}"
                )
                return False

            # Verify authentication by accessing a protected resource
            verify_response = self.client.get("/events.php")
            if "Login Required" in verify_response.text:
                logger.warning("Authentication verification failed")
                return False

            self._authenticated = True
            logger.info("Successfully authenticated with ZwiftPower via OAuth")
            return True

        except httpx.HTTPError as e:
            raise ZwiftPowerAuthError(f"OAuth authentication failed: {e}") from e

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> httpx.Response:
        """
        Make a GET request to ZwiftPower.

        Args:
            path: URL path (e.g., "/events.php")
            params: Query parameters
            retry: Whether to retry on failure

        Returns:
            HTTP response

        Raises:
            ZwiftPowerConnectionError: On network error
            ZwiftPowerRateLimitError: On rate limiting
        """
        retries = MAX_RETRIES if retry else 1

        for attempt in range(retries):
            try:
                response = self.client.get(path, params=params)

                if response.status_code == 429:
                    if attempt < retries - 1:
                        delay = RETRY_DELAY * (2**attempt)
                        logger.warning(f"Rate limited, retrying in {delay}s...")
                        time.sleep(delay)
                        continue
                    raise ZwiftPowerRateLimitError("Rate limited by ZwiftPower")

                response.raise_for_status()
                return response

            except httpx.HTTPStatusError as e:
                if attempt < retries - 1:
                    delay = RETRY_DELAY * (2**attempt)
                    logger.warning(
                        f"Request failed ({e.response.status_code}), "
                        f"retrying in {delay}s..."
                    )
                    time.sleep(delay)
                    continue
                raise ZwiftPowerConnectionError(f"HTTP error: {e}") from e

            except httpx.RequestError as e:
                if attempt < retries - 1:
                    delay = RETRY_DELAY * (2**attempt)
                    logger.warning(f"Connection error, retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                raise ZwiftPowerConnectionError(f"Connection error: {e}") from e

        raise ZwiftPowerConnectionError("Max retries exceeded")

    def get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Make a GET request and parse JSON response.

        Args:
            path: URL path
            params: Query parameters

        Returns:
            Parsed JSON data
        """
        response = self.get(path, params)
        return response.json()

    def get_html(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> BeautifulSoup:
        """
        Make a GET request and parse HTML response.

        Args:
            path: URL path
            params: Query parameters

        Returns:
            BeautifulSoup parsed HTML
        """
        response = self.get(path, params)
        return BeautifulSoup(response.text, "lxml")

    @property
    def is_authenticated(self) -> bool:
        """Check if client is authenticated."""
        return self._authenticated

    def get_events_with_results(self, days: int = 7) -> list[dict[str, Any]]:
        """
        Get list of events with results from the past N days.

        Args:
            days: Number of days to look back (default 7)

        Returns:
            List of event dictionaries
        """
        # Try cached endpoint first (faster)
        cache_url = f"/cache3/lists/0_zwift_event_list_results_{days}.json"
        try:
            response = self.get(cache_url)
            data = response.json()
            if data and "data" in data:
                return data["data"]
        except Exception as e:
            logger.debug(f"Cache endpoint failed: {e}, trying dynamic API")

        # Fall back to dynamic API
        api_url = f"/api3.php?do=zwift_event_list_results&DAYS={days}"
        try:
            response = self.get(api_url)
            data = response.json()
            if data and "data" in data:
                return data["data"]
        except Exception as e:
            logger.warning(f"Dynamic API also failed: {e}")

        return []

    def get_event_results(self, event_id: str | int) -> list[dict[str, Any]]:
        """
        Get results for a specific event.

        Args:
            event_id: ZwiftPower event ID

        Returns:
            List of result dictionaries
        """
        # Try cached results first
        cache_url = f"/cache3/results/{event_id}_view.json"
        try:
            response = self.get(cache_url)
            data = response.json()
            if data and "data" in data:
                return data["data"]
        except Exception as e:
            logger.debug(f"Cache results failed: {e}, trying dynamic API")

        # Fall back to dynamic API
        api_url = f"/api3.php?do=event_results&zid={event_id}"
        try:
            response = self.get(api_url)
            data = response.json()
            if data and "data" in data:
                return data["data"]
        except Exception as e:
            logger.warning(f"Dynamic API results also failed: {e}")

        return []
