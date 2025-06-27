# steam_info_extractor.py
import requests
from urllib.parse import urlparse
import re
import json
import logging # 导入 logging 模块

# 获取当前模块的日志器
logger = logging.getLogger(__name__)

class SteamInfoExtractor:
    """
    从Steam URL中提取AppID，并从Steam Web API获取游戏信息的类。
    """
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    # Steam Web API appdetails 接口
    STEAM_API_APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails/"

    def __init__(self):
        logger.debug("SteamInfoExtractor 实例初始化。")
        pass

    def extract_appid_from_url(self, steam_community_url: str) -> str | None:
        """
        从Steam社区推荐URL中提取AppID。
        例如：https://steamcommunity.com/id/EnderAvaritia/recommended/2875610?tscn=1751003141 -> 2875610
        """
        logger.info(f"尝试从URL提取AppID: {steam_community_url}")
        parsed_url = urlparse(steam_community_url)
        path_segments = parsed_url.path.split('/')
        
        for i in range(len(path_segments) - 1, -1, -1):
            if path_segments[i].isdigit():
                appid = path_segments[i]
                logger.info(f"从URL路径中提取到AppID: {appid}")
                return appid
        
        match = re.search(r'/(?:recommended|app)/(\d+)', steam_community_url)
        if match:
            appid = match.group(1)
            logger.info(f"通过正则表达式从URL中提取到AppID: {appid}")
            return appid
            
        logger.warning(f"未能从URL中提取AppID: {steam_community_url}")
        return None

    def get_game_info_from_appid(self, appid: str) -> dict | None:
        """
        根据AppID从Steam Web API获取游戏名和发行商名。
        已修改为请求简体中文数据 (l=schinese)。
        """
        if not appid:
            logger.error("AppID为空，无法获取游戏信息。")
            return None

        api_url = f"{self.STEAM_API_APP_DETAILS_URL}?appids={appid}&l=schinese"
        headers = {"User-Agent": self.USER_AGENT}
        logger.info(f"正在请求Steam API获取AppID {appid} 的信息，URL: {api_url}")

        try:
            response = requests.get(api_url, headers=headers, timeout=10)
            response.raise_for_status()

            data = response.json()
            logger.debug(f"Steam API响应数据 (AppID {appid}): {data}")

            app_data_wrapper = data.get(appid)

            if not app_data_wrapper or not app_data_wrapper.get('success'):
                logger.warning(f"Steam API返回失败或AppID {appid} 不存在。响应: {data}")
                return None

            game_data = app_data_wrapper.get('data')
            if not game_data:
                logger.warning(f"AppID {appid} 的数据结构不完整。")
                return None

            game_name = game_data.get('name', "未知游戏名")
            
            publishers = game_data.get('publishers')
            publisher_name = "未知发行商"
            if publishers and isinstance(publishers, list) and len(publishers) > 0:
                publisher_name = ", ".join(publishers) 
                logger.info(f"AppID {appid} 游戏名: '{game_name}', 发行商: '{publisher_name}'")
            else:
                logger.warning(f"AppID {appid} 未找到发行商信息。")

            return {
                "appid": appid,
                "game_name": game_name,
                "publisher_name": publisher_name
            }

        except requests.exceptions.RequestException as e:
            logger.error(f"请求Steam API失败 (AppID {appid}): {e}")
            return None
        except json.JSONDecodeError:
            logger.error(f"Steam API返回了无效的JSON响应 (AppID {appid})。响应内容: {response.text[:200]}...")
            return None
        except Exception as e:
            logger.exception(f"处理Steam API响应失败 (AppID {appid})。") # exception 会打印堆栈信息
            return None

# 示例用法 (仅用于测试此模块)
if __name__ == "__main__":
    # 在模块测试时，也配置一下日志，否则不会有输出
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    extractor = SteamInfoExtractor()
    test_url = "https://steamcommunity.com/id/EnderAvaritia/recommended/2875610?tscn=1751003141"
    
    appid = extractor.extract_appid_from_url(test_url)
    if appid:
        print(f"提取到的AppID: {appid}")
        game_info = extractor.get_game_info_from_appid(appid)
        if game_info:
            print(f"游戏信息 (简体中文): {game_info}")
        else:
            print("未能获取游戏信息。")
    else:
        print("未能从URL中提取AppID。")

    test_url_2 = "https://steamcommunity.com/app/1091500/reviews/?browsefilter=toprated&snr=1_5_9__20" # Cyberpunk 2077
    appid_2 = extractor.extract_appid_from_url(test_url_2)
    if appid_2:
        print(f"\n提取到的AppID (测试2): {appid_2}")
        game_info_2 = extractor.get_game_info_from_appid(appid_2)
        if game_info_2:
            print(f"游戏信息 (测试2 - 简体中文): {game_info_2}")
        else:
            print("未能获取游戏信息 (测试2)。")
    
    test_url_3 = "https://steamcommunity.com/app/570/reviews/?browsefilter=toprated&snr=1_5_9__20" # Dota 2 (Valve)
    appid_3 = extractor.extract_appid_from_url(test_url_3)
    if appid_3:
        print(f"\n提取到的AppID (测试3): {appid_3}")
        game_info_3 = extractor.get_game_info_from_appid(appid_3)
        if game_info_3:
            print(f"游戏信息 (测试3 - 简体中文): {game_info_3}")
        else:
            print("未能获取游戏信息 (测试3)。")

