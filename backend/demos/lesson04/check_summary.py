from app.db.models import Episode


def summary_length(ep: Episode) -> int:
    return len(ep.plot_summary)
