import requests
import time
from typing import Dict, Any, List, Optional, Tuple

class RailwayApiError(Exception):
    pass

class TokenExpiredError(RailwayApiError):
    pass

class RateLimitError(RailwayApiError):
    pass

class RailwayApiClient:
    BASE_URL = "https://railspaapi.shohoz.com/v1.0/web"
    SEARCH_ENDPOINT = f"{BASE_URL}/bookings/search-trips-v2"

    def __init__(self, token: str, uudid: str, ssdk: Optional[str] = None):
        self.token = token.strip()
        self.uudid = uudid.strip()
        self.ssdk = ssdk.strip() if ssdk else ""
        self.session = requests.Session()

    def update_credentials(self, token: str, uudid: str, ssdk: Optional[str] = None):
        self.token = token.strip()
        self.uudid = uudid.strip()
        self.ssdk = ssdk.strip() if ssdk else ""

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Authorization": f"Bearer {self.token}",
            "Connection": "keep-alive",
            "Origin": "https://eticket.railway.gov.bd",
            "Referer": "https://eticket.railway.gov.bd/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "X-Device-Id": self.uudid,
            "X-Requested-With": "XMLHttpRequest"
        }
        if self.ssdk:
            headers["X-Device-Key"] = self.ssdk
        return headers

    def search_trips(
        self,
        from_city: str,
        to_city: str,
        date_of_journey: str,
        seat_class: str = "ALL",
        check_all_classes: bool = True
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], float]:
        """
        Queries Shohoz API for available trains.
        Returns:
            - available_matches: list of dicts with trains that have online seats > 0
            - all_trains: list of dicts summarizing each train found
            - latency_ms: response latency in milliseconds
        """
        # Shohoz accepts a class param; if ALL or ANY, pass SNIGDHA as default query param
        query_class = "SNIGDHA" if seat_class.upper() in ["ALL", "ANY", ""] else seat_class
        params = {
            "from_city": from_city,
            "to_city": to_city,
            "date_of_journey": date_of_journey,
            "seat_class": query_class
        }


        start_t = time.time()
        try:
            resp = self.session.get(
                self.SEARCH_ENDPOINT,
                headers=self._get_headers(),
                params=params,
                timeout=8
            )
        except requests.RequestException as e:
            raise RailwayApiError(f"Network error querying Shohoz API: {e}")

        latency_ms = (time.time() - start_t) * 1000

        if resp.status_code == 401:
            raise TokenExpiredError("Access Token is invalid or expired. Please update session token.")
        elif resp.status_code == 429:
            raise RateLimitError("Rate limit exceeded (HTTP 429). Waiting for backoff.")
        elif resp.status_code != 200:
            raise RailwayApiError(f"Unexpected response from Shohoz API: HTTP {resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            raise RailwayApiError("Failed to parse JSON response from Shohoz API")

        # Automatically update device key if returned in response
        extra_key = data.get("data", {}).get("device_key")
        if extra_key and extra_key != self.ssdk:
            self.ssdk = extra_key

        trains = data.get("data", {}).get("trains", [])
        available_matches = []
        all_trains = []

        for train in trains:
            # Bangladesh Railway API uses 'trip_number' for train name (e.g. 'PARABAT EXPRESS (710)')
            train_name = train.get("trip_number") or train.get("train_name", "Unknown Train")
            departure_time = train.get("departure_date_time", "")
            seat_types = train.get("seat_types", [])

            train_info = {
                "train_name": train_name,
                "departure_time": departure_time,
                "classes": {}
            }

            for st in seat_types:
                st_class = st.get("type", "")
                st_fare = st.get("fare", 0)
                seat_counts = st.get("seat_counts", {})
                online = int(seat_counts.get("online", 0))
                offline = int(seat_counts.get("offline", 0))

                train_info["classes"][st_class] = {
                    "online": online,
                    "offline": offline,
                    "fare": st_fare
                }

                # Check if this class matches the requested seat_class (or if checking all seats)
                is_target_class = (
                    check_all_classes
                    or seat_class.upper() in ["ALL", "ANY", ""]
                    or st_class.upper() == seat_class.upper()
                )
                if is_target_class and online > 0:
                    available_matches.append({
                        "train_name": train_name,
                        "departure_time": departure_time,
                        "seat_class": st_class,
                        "online_seats": online,
                        "offline_seats": offline,
                        "fare": st_fare,
                        "date_of_journey": date_of_journey
                    })

            all_trains.append(train_info)

        return available_matches, all_trains, latency_ms
