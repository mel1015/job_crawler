from bs4 import BeautifulSoup

from job_crawler.crawlers.base import IMAGE_ONLY_PLACEHOLDER
from job_crawler.crawlers.saramin import SaraminCrawler
from job_crawler.scoring.claude_batch import _is_image_only

SUMMARY = """
<div class="jv_cont jv_summary">
  <dl><dt>경력</dt><dd>경력 3년 ↑</dd></dl>
  <dl><dt>우대사항</dt><dd><button>우대사항 상세보기</button></dd></dl>
  <dl><dt>자격요건</dt><dd><button>자격요건 상세보기</button></dd></dl>
</div>
"""


def _extract(detail_html: str):
    soup = BeautifulSoup(f"<div class='wrap_jv_cont'>{SUMMARY}{detail_html}</div>", "html.parser")
    return SaraminCrawler(user_agent="test")._extract_body(soup)


def test_detail_jd_is_kept_after_summary():
    # 요약 블록에도 "자격요건"/"우대사항" 문구가 있어 예전에는 요약만 저장하고 JD를 버렸다
    body, images = _extract(
        """<div class="jv_cont jv_detail"><h2>상세요강</h2>
        <img src="https://static.saraminimage.co.kr/static/hiring/images/template/toptype/it3.webp">
        <p>[주요 업무] 보험 Core 및 채널 시스템의 분석, 설계, 개발 및 운영 주도</p>
        <p>[자격 요건] Java Front-End/Back-End 개발 및 운영 유지보수 경력 3년 이상</p></div>"""
    )
    assert "경력 3년" in body
    assert "보험 Core 및 채널 시스템" in body
    assert images == []


def test_image_only_detail_collects_jd_images():
    body, images = _extract(
        """<div class="jv_cont jv_detail"><h2>상세요강</h2>
        <img src="https://pds.saramin.co.kr/recruit/recruit/202611/24/41cf70_recruit.png">
        <img src="https://www.saraminimage.co.kr/recruit/bbs_recruit7/watermark_match_basic.png"></div>"""
    )
    assert images == ["https://pds.saramin.co.kr/recruit/recruit/202611/24/41cf70_recruit.png"]
    assert IMAGE_ONLY_PLACEHOLDER in body
    assert _is_image_only(body)


def test_image_proxy_is_kept_and_expired_notice_is_skipped():
    body, images = _extract(
        """<div class="jv_cont jv_detail expired"><p>마감된 공고입니다</p></div>
        <div class="jv_cont jv_detail"><h2>상세요강</h2>
        <img src="https://www.saraminimage.co.kr?url=http://example.com/img/java.jpg"></div>"""
    )
    assert images == ["https://www.saraminimage.co.kr?url=http://example.com/img/java.jpg"]
