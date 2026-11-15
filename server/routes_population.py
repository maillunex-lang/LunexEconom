"""Read API for households and housing (EX-05). Documented in docs/POPULATION.md. Not drawn in the client."""
import households
import housing_market


def handle_get(db, ph, path, query):
    city = (query.get("city") or [None])[0]
    if path == "/population":
        payload = households.view(db, ph, city or None)
        if payload is None:
            return 400, {"error": "unknown_city"}
        if city:
            payload["city"] = payload["cities"][0]
        return 200, payload
    if path == "/housing":
        if not city:
            return 400, {"error": "city_required"}
        import geo
        if geo.get_city(city) is None:
            return 400, {"error": "unknown_city"}
        return 200, housing_market.view(db, ph, city)
    return 404, {"error": "not_found"}
