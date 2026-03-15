from collections import Counter
from threading import Lock


class AnalyticsAggregator:
    def __init__(self) -> None:
        self._lock = Lock()
        self._products = Counter()
        self._customers = Counter()
        self._seen_order_ids: set[str] = set()

        self._orders_total = 0
        self._error_events_total = 0
        self._publish_error_events = 0
        self._processing_events_total = 0

        self._persist_ms_sum = 0.0
        self._persist_ms_count = 0
        self._publish_ms_sum = 0.0
        self._publish_ms_count = 0
        self._notification_ms_sum = 0.0
        self._notification_ms_count = 0

    def add_created(
        self,
        order_id: str | None,
        customer: str,
        items: list[dict[str, int | str]],
        persist_ms: float | None,
    ) -> None:
        with self._lock:
            if order_id and order_id in self._seen_order_ids:
                return
            if order_id:
                self._seen_order_ids.add(order_id)

            self._orders_total += 1
            self._customers[customer] += 1
            for item in items:
                sku = str(item["sku"])
                qty = int(item["qty"])
                self._products[sku] += qty

            if persist_ms is not None:
                self._persist_ms_sum += float(persist_ms)
                self._persist_ms_count += 1

    def add_error(self, stage: str) -> None:
        with self._lock:
            self._error_events_total += 1
            if stage == "publish":
                self._publish_error_events += 1

    def add_processing(
        self,
        service: str,
        status: str,
        metric: str | None,
        duration_ms: float | None,
    ) -> None:
        with self._lock:
            self._processing_events_total += 1
            if status.lower() == "error":
                self._error_events_total += 1

            if service == "writer" and metric == "publish" and duration_ms is not None:
                self._publish_ms_sum += float(duration_ms)
                self._publish_ms_count += 1

            if service == "notification" and duration_ms is not None:
                self._notification_ms_sum += float(duration_ms)
                self._notification_ms_count += 1

    def snapshot(self) -> dict:
        with self._lock:
            tracked_events = self._orders_total + self._processing_events_total
            system_error_percentage = (
                round((self._error_events_total / tracked_events) * 100, 2)
                if tracked_events > 0
                else 0.0
            )
            publish_error_percentage = (
                round((self._publish_error_events / self._orders_total) * 100, 2)
                if self._orders_total > 0
                else 0.0
            )

            return {
                "total_orders_seen": self._orders_total,
                "top_products": [
                    {"sku": sku, "total_qty": qty}
                    for sku, qty in self._products.most_common(5)
                ],
                "most_frequent_customer": (
                    {
                        "customer": self._customers.most_common(1)[0][0],
                        "orders": self._customers.most_common(1)[0][1],
                    }
                    if self._customers
                    else None
                ),
                "error_rates": {
                    "publish_error_percentage": publish_error_percentage,
                    "system_error_percentage": system_error_percentage,
                    "error_events": self._error_events_total,
                },
                "avg_times_ms": {
                    "persist_order_postgres": round(self._persist_ms_sum / self._persist_ms_count, 2)
                    if self._persist_ms_count
                    else None,
                    "publish_event_rabbitmq": round(self._publish_ms_sum / self._publish_ms_count, 2)
                    if self._publish_ms_count
                    else None,
                    "notification": round(self._notification_ms_sum / self._notification_ms_count, 2)
                    if self._notification_ms_count
                    else None,
                },
            }
