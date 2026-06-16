import asyncio

from api.live import Live
from api.logger import logger


class LiveProcessor:
    @staticmethod
    async def run_live(live: Live, speed: float = 1.0, should_stop=None):
        """Loop until the live task duration is satisfied."""
        live_status = live.get_status()
        if not live_status:
            logger.error("Failed to get live status, unable to continue")
            return False

        try:
            duration = live_status.get("temp", {}).get("data", {}).get("duration", 0)
            if not duration:
                logger.warning("Unable to get live duration, fallback to 30 minutes")
                duration = 30 * 60
        except Exception as exc:
            logger.error(f"Failed to parse live duration: {exc}")
            return False

        adjusted_duration = duration / speed
        total_minutes = (int(adjusted_duration) + 59) // 60
        logger.info("Start live task '{}', total {} minute(s) after speed adjustment", live.name, total_minutes)

        for index in range(total_minutes):
            if callable(should_stop) and should_stop():
                logger.info("Live task cancelled: {}", live.name)
                return False

            logger.info("Live '{}' progress {}/{} minute(s)", live.name, index + 1, total_minutes)
            success = live.do_finish()
            if not success:
                logger.warning("Live minute {} submit failed, retrying once", index + 1)
                retry_sleep = 5.0
                while retry_sleep > 0:
                    if callable(should_stop) and should_stop():
                        logger.info("Live task cancelled: {}", live.name)
                        return False
                    interval = min(0.5, retry_sleep)
                    await asyncio.sleep(interval)
                    retry_sleep -= interval
                live.do_finish()

            sleep_time = 59 / speed
            while sleep_time > 0:
                if callable(should_stop) and should_stop():
                    logger.info("Live task cancelled: {}", live.name)
                    return False
                interval = min(1.0, sleep_time)
                await asyncio.sleep(interval)
                sleep_time -= interval

        logger.success("Live '{}' completed", live.name)
        return True
