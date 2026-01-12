"""Avatar image downloading and management for website generation."""

import logging
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


def download_avatar(
    rider_id: str,
    output_dir: Path,
    timeout: int = 10,
) -> Path | None:
    """
    Download a rider's avatar from ZwiftPower.

    Args:
        rider_id: ZwiftPower rider ID
        output_dir: Directory to save avatar images
        timeout: Request timeout in seconds

    Returns:
        Path to downloaded avatar, or None if download failed
    """
    # Create avatars directory if it doesn't exist
    avatars_dir = output_dir / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)

    avatar_filename = f"{rider_id}.jpg"
    avatar_path = avatars_dir / avatar_filename

    # Skip if already downloaded
    if avatar_path.exists():
        return avatar_path

    # Try to download from ZwiftPower
    url = f"https://zwiftpower.com/cache3/profile/{rider_id}_sml.jpg"

    try:
        # Add headers to mimic browser request
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://zwiftpower.com/",
        }

        response = requests.get(url, headers=headers, timeout=timeout, stream=True)

        if response.status_code == 200:
            # Save the image
            with avatar_path.open("wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.debug(f"Downloaded avatar for rider {rider_id}")
            return avatar_path
        else:
            logger.debug(
                f"Failed to download avatar for rider {rider_id}: HTTP {response.status_code}"
            )
            return None

    except Exception as e:
        logger.debug(f"Error downloading avatar for rider {rider_id}: {e}")
        return None


def download_avatars_for_standings(
    tour_standings,
    output_dir: Path,
) -> dict[str, str]:
    """
    Download avatars for all riders in tour standings.

    Args:
        tour_standings: TourStandings object with GC standings
        output_dir: Directory to save avatar images

    Returns:
        Dict mapping rider_id to relative avatar path
    """
    avatar_paths = {}
    rider_ids = set()

    # Collect all unique rider IDs from both groups
    for standing in tour_standings.group_a.standings:
        rider_ids.add(standing.rider_id)

    for standing in tour_standings.group_b.standings:
        rider_ids.add(standing.rider_id)

    logger.info(f"Downloading avatars for {len(rider_ids)} riders")

    # Download avatars
    for rider_id in rider_ids:
        avatar_path = download_avatar(rider_id, output_dir)
        if avatar_path:
            # Store relative path for HTML templates
            avatar_paths[rider_id] = f"avatars/{rider_id}.jpg"

    logger.info(f"Successfully downloaded {len(avatar_paths)} avatars")

    return avatar_paths
