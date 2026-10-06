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

    @staticmethod
    def is_train_allowed(train_name: str, departure_time: str = "", allowed_trains: Optional[List[str]] = None) -> bool:
        """
        Checks if a train matches any of the allowed train patterns.
        If allowed_trains is empty or contains 'ALL', any train is allowed.
        """
        if not allowed_trains:
            return True

        normalized = [t.strip().upper() for t in allowed_trains if t.strip()]
        if not normalized or "ALL" in normalized:
            return True

        t_upper = train_name.upper()
        dep_upper = str(departure_time).upper()

        for pattern in normalized:
            # Direct match (e.g. "PARABAT" in "PARABAT EXPRESS (709)")
            if pattern in t_upper:
                return True

            # Check individual keywords if full phrase doesn't match directly
            keywords = [w for w in pattern.split() if len(w) > 3 and not w.isdigit()]
            if keywords and all(kw in t_upper for kw in keywords):
                return True

        return False

    @classmethod
    def matches_rules(
        cls,
        train_name: str,
        departure_time: str,
        st_class: str,
        rules: List[Dict[str, Any]],
        check_all_classes: bool = False
    ) -> bool:
        """
        Evaluates whether a train and seat class matches any of the specified rules.
        Each rule contains 'trains' (list of train patterns) and 'seat_classes' (list of allowed classes).
        """
        if check_all_classes:
            return any(cls.is_train_allowed(train_name, departure_time, r.get("trains")) for r in rules)

        st_upper = st_class.strip().upper()
        for r in rules:
            trains_pattern = r.get("trains", ["ALL"])
            if cls.is_train_allowed(train_name, departure_time, trains_pattern):
                classes = [c.strip().upper() for c in r.get("seat_classes", [])]
                if not classes or "ALL" in classes or "ANY" in classes:
                    return True
                if st_upper in classes:
                    return True
        return False

    def search_trips(
        self,
        from_city: str,
        to_city: str,
        date_of_journey: str,
        seat_classes: Optional[List[str]] = None,
        seat_class: str = "ALL",
        check_all_classes: bool = False,
        allowed_trains: Optional[List[str]] = None,
        rules: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], float]:
        """
        Queries Shohoz API for available trains.
        Returns:
            - available_matches: list of dicts with trains that have online seats > 0
                                 matching allowed rules/trains and target seat classes.
            - all_trains: list of dicts summarizing each train found
            - latency_ms: response latency in milliseconds
        """
        # Build effective rules if not directly provided
        if not rules:
            effective_classes = seat_classes if seat_classes else ([seat_class] if seat_class not in ["ALL", "ANY", ""] else ["ALL"])
            rules = [{
                "trains": allowed_trains or ["ALL"],
                "seat_classes": effective_classes
            }]

        # Determine query parameter for class
        all_classes = []
        for r in rules:
            all_classes.extend(r.get("seat_classes", []))

        if "SNIGDHA" in [c.upper() for c in all_classes]:
            query_class = "SNIGDHA"
        elif all_classes and all_classes[0].upper() not in ["ALL", "ANY"]:
            query_class = all_classes[0].upper()
        elif seat_classes and len(seat_classes) > 0 and seat_classes[0].upper() not in ["ALL", "ANY"]:
            query_class = seat_classes[0].upper()
        else:
            query_class = "SNIGDHA"

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
            # Bangladesh Railway API uses 'trip_number' for train name (e.g. 'PARABAT EXPRESS (709)')
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

                # Evaluate against defined rules
                if online > 0 and self.matches_rules(train_name, departure_time, st_class, rules, check_all_classes):
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
