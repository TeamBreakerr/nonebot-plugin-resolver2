import math
import re

import aiohttp

from ..constant import COMMON_HEADER
from ..exception import ParseException
from .base import BaseParser, VideoAuthor, VideoInfo

WEIBO_SINGLE_INFO = "https://m.weibo.cn/statuses/show?id={}"


class WeiBo(BaseParser):
    async def parse_share_url(self, share_url: str) -> VideoInfo:
        """解析微博分享链接"""
        # https://video.weibo.com/show?fid=1034:5145615399845897
        if match := re.search(r"https://video\.weibo\.com/show\?fid=(\d+:\d+)", share_url):
            return await self.parse_fid(match.group(1))
        # https://m.weibo.cn/detail/4976424138313924
        elif match := re.search(r"m\.weibo\.cn(?:/detail|/status)?/([A-Za-z\d]+)", share_url):
            weibo_id = match.group(1)
        # https://weibo.com/tv/show/1034:5007449447661594?mid=5007452630158934
        elif match := re.search(r"mid=([A-Za-z\d]+)", share_url):
            weibo_id = mid2id(match.group(1))
        # https://weibo.com/1707895270/5006106478773472
        elif match := re.search(r"(?<=weibo.com/)[A-Za-z\d]+/([A-Za-z\d]+)", share_url):
            weibo_id = match.group(1)
        # 无法获取到id则返回失败信息
        else:
            raise ParseException("无法获取到微博的 id")

        return await self.parse_weibo_id(weibo_id)

    async def parse_fid(self, fid: str) -> VideoInfo:
        """
        解析带 fid 的微博视频
        """
        req_url = f"https://h5.video.weibo.com/api/component?page=/show/{fid}"
        headers = {
            "Referer": f"https://h5.video.weibo.com/show/{fid}",
            "Content-Type": "application/x-www-form-urlencoded",
            **self.default_headers,
        }
        post_content = 'data={"Component_Play_Playinfo":{"oid":"' + fid + '"}}'
        async with aiohttp.ClientSession() as session:
            async with session.post(req_url, headers=headers, data=post_content) as response:
                response.raise_for_status()
                json_data = await response.json()
        data = json_data["data"]["Component_Play_Playinfo"]

        video_url = data["stream_url"]
        if len(data["urls"]) > 0:
            # stream_url码率最低，urls中第一条码率最高
            _, first_mp4_url = next(iter(data["urls"].items()))
            video_url = f"https:{first_mp4_url}"

        video_info = VideoInfo(
            video_url=video_url,
            cover_url="https:" + data["cover_image"],
            title=data["title"],
            author=VideoAuthor(
                uid=str(data["user"]["id"]),
                name=data["author"],
                avatar="https:" + data["avatar"],
            ),
        )
        return video_info

    async def parse_weibo_id(self, weibo_id: str) -> VideoInfo:
        """解析微博 id"""
        headers = {
            "accept": "application/json",
            "cookie": "_T_WM=40835919903; WEIBOCN_FROM=1110006030; MLOGIN=0; XSRF-TOKEN=4399c8",
            "Referer": f"https://m.weibo.cn/detail/{weibo_id}",
            **COMMON_HEADER,
        }

        # 请求数据
        async with aiohttp.ClientSession() as session:
            async with session.get(WEIBO_SINGLE_INFO.format(weibo_id), headers=headers) as resp:
                if resp.status != 200:
                    raise ParseException(f"获取数据失败 {resp.status} {resp.reason}")
                if "application/json" not in resp.headers.get("content-type", ""):
                    raise ParseException("获取数据失败 content-type is not application/json")
                resp_json = await resp.json()

        weibo_data = resp_json.get("data", {})
        text = weibo_data.get("text", "")
        status_title = weibo_data.get("status_title", "")
        source = weibo_data.get("source", "")
        region_name = weibo_data.get("region_name", "")
        pics = weibo_data.get("pics") or []
        page_info = weibo_data.get("page_info") or {}

        # 处理图集
        if pics:
            pics = [x["large"]["url"] for x in pics]

        # 安全获取视频 URL
        urls = page_info.get("urls") or {}
        # 优先 mp4_720p_mp4，其次 mp4_hd_mp4，否则空字符串
        video_url = urls.get("mp4_720p_mp4") or urls.get("mp4_hd_mp4") or ""

        # 去除 HTML 标签，拼接标题
        clean_text = re.sub(r"<[^>]+>", "", text)
        title = f"{clean_text}\n{status_title}\n{source}\t{region_name}" if status_title or region_name else clean_text

        return VideoInfo(
            title=title,
            video_url=video_url,
            images=pics,
            author=VideoAuthor(name=source),
        )


# 定义 base62 编码字符表
ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def base62_encode(number: int) -> str:
    """将数字转换为 base62 编码"""
    if number == 0:
        return "0"

    result = ""
    while number > 0:
        result = ALPHABET[number % 62] + result
        number //= 62

    return result


def mid2id(mid: str) -> str:
    """将微博 mid 转换为 id"""
    mid = str(mid)[::-1]  # 反转输入字符串
    size = math.ceil(len(mid) / 7)  # 计算每个块的大小
    result = []

    for i in range(size):
        # 对每个块进行处理并反转
        s = mid[i * 7 : (i + 1) * 7][::-1]
        # 将字符串转为整数后进行 base62 编码
        s = base62_encode(int(s))
        # 如果不是最后一个块并且长度不足4位，进行左侧补零操作
        if i < size - 1 and len(s) < 4:
            s = "0" * (4 - len(s)) + s
        result.append(s)

    result.reverse()  # 反转结果数组
    return "".join(result)  # 将结果数组连接成字符串
