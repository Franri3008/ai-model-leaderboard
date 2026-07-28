def coerce_seen_registry(raw):
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    if isinstance(raw, list):
        return {
            str(item["key"]): str(item["first_seen"])
            for item in raw
            if isinstance(item, dict) and "key" in item and "first_seen" in item
        }
    return {}

def select_new_tracking_issues(issues, previous_signatures, signature, baseline_ready):
    if not baseline_ready:
        return []
    previous = {str(value) for value in previous_signatures}
    return [issue for issue in issues if signature(issue) not in previous]

def register_untracked_models(groups, seen, today, baseline_ready):
    new_groups = []
    for group in groups:
        key = group["norm_name"]
        if key in seen:
            continue
        seen[key] = today
        if baseline_ready:
            new_groups.append(group)
    return new_groups
