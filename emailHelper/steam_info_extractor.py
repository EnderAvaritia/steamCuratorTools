import requests
from lxml import html
import re
import logging

logger = logging.getLogger(__name__)

class SteamInfoExtractor:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
        })

    def extract_appid_from_url(self, url: str) -> str:
        """
        从 Steam URL 中提取 AppID。支持商店页面和评测页面。
        """
        if url is None:  # 检查 URL 是否为 None
            logger.warning("传入的 URL 为 None")
            return None
        try:
            # 尝试从商店页面 URL 提取
            match = re.search(r"app/(\d+)", url)
            if match:
                return match.group(1)

            # 尝试从评测页面 URL 提取
            match = re.search(r"recommended/(\d+)", url)
            if match:
                return match.group(1)

            logger.warning(f"无法从URL提取AppID: {url}")
            return None
        except Exception as e:
            logger.exception(f"提取AppID时发生错误: {url}")
            return None

    def get_game_info_from_appid(self, appid: str) -> dict:
        """
        从 Steam API 获取游戏信息，包括游戏名和发行商。
        """
        url = f"https://store.steampowered.com/api/appdetails?appids={appid}&l=schinese"
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()  # 检查HTTP错误
            data = response.json()

            if appid in data and data[appid]['success']:
                game_name = data[appid]['data'].get('name', '')
                publishers = data[appid]['data'].get('publishers', [])
                publisher_name = ', '.join(publishers) if publishers else ''

                if not game_name:
                    logger.warning(f"无法从API提取游戏名: {url}")
                if not publisher_name:
                    logger.warning(f"无法从API提取发行商名: {url}")

                return {
                    "game_name": game_name,
                    "publisher_name": publisher_name
                }
            else:
                logger.warning(f"AppID {appid} 在 API 响应中不存在或请求失败: {url}")
                return {}

        except requests.exceptions.RequestException as e:
            logger.error(f"网络请求错误: {url} - {e}")
            return {}
        except Exception as e:
            logger.exception(f"解析 API 响应时发生错误: {url}")
            return {}

if __name__ == '__main__':
    # 示例用法
    extractor = SteamInfoExtractor()
    appid = "730"  # Counter-Strike: Global Offensive
    game_info = extractor.get_game_info_from_appid(appid)

    if game_info:
        print(f"游戏名: {game_info['game_name']}")
        print(f"发行商: {game_info['publisher_name']}")
    else:
        print(f"无法获取 AppID {appid} 的游戏信息")
