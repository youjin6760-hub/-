import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse, urljoin, parse_qs

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time


ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw"
RAW_DIR.mkdir(exist_ok=True)

DEBUG_DIR = ROOT / "debug"
DEBUG_DIR.mkdir(exist_ok=True)

IMG_DIR = ROOT / "images"
IMG_DIR.mkdir(exist_ok=True)

TARGET_MAIN_URL = "https://www.dataedupt.kr/sub/main/main.php"
ALLOWED_HOSTS = {
    "www.dataedupt.kr",
    "dataedupt.kr",
}


def load_config():
    with open(ROOT / "run_config.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        return [data]

    if isinstance(data, list):
        return data

    raise ValueError("run_config.json은 객체 또는 객체 리스트 형식이어야 합니다.")


EXPLANATION_BODY_SELECTORS = [
    "div.tg2g2 div.more-c div.t1",  # 기존 구조
    "div.tg2g2 > div.t1",           # 예비문제 구조
]

EXPLANATION_KEYWORD_SELECTORS = [
    "div.tg2g2 div.more-c div.t2 a.tag",  # 기존 구조
    "div.tg2g2 div.t2 a.tag",             # 예비문제 구조
    "div.tg2g2 a.tag",
]


def get_explanation_body_locator(page):
    for sel in EXPLANATION_BODY_SELECTORS:
        loc = page.locator(sel).first
        try:
            if loc.count() > 0 and loc.is_visible(timeout=1000):
                return loc
        except Exception:
            pass

    for sel in EXPLANATION_BODY_SELECTORS:
        loc = page.locator(sel).first
        try:
            if loc.count() > 0:
                return loc
        except Exception:
            pass

    return page.locator(EXPLANATION_BODY_SELECTORS[0]).first


def sanitize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def safe_text(locator):
    try:
        return sanitize_text(locator.inner_text())
    except Exception:
        return ""


def safe_attr(locator, attr_name: str):
    try:
        return locator.get_attribute(attr_name) or ""
    except Exception:
        return ""


def norm_id_text(x: str):
    x = (x or "").strip()
    x = re.sub(r"[^\w가-힣]+", "_", x)
    x = re.sub(r"_+", "_", x).strip("_")
    return x


def make_question_id(course_name, set_name, subject_name, question_no, sub_title=None):
    # 하위 카드가 있을 때만 sub_title 포함
    if sub_title:
        if subject_name:
            return f"{norm_id_text(course_name)}_{norm_id_text(set_name)}_{norm_id_text(subject_name)}_{norm_id_text(sub_title)}_{question_no}"
        return f"{norm_id_text(course_name)}_{norm_id_text(set_name)}_{norm_id_text(sub_title)}_{question_no}"

    # 하위 카드가 없을 때는 기존 형식 유지
    if subject_name:
        return f"{norm_id_text(course_name)}_{norm_id_text(set_name)}_{norm_id_text(subject_name)}_{question_no}"
    return f"{norm_id_text(course_name)}_{norm_id_text(set_name)}_{question_no}"


def parse_question_range(question_range: str):
    if question_range == "all":
        return None
    m = re.match(r"(\d+)\s*-\s*(\d+)", question_range)
    if not m:
        raise ValueError("question_range는 '1-10' 또는 'all' 형식이어야 합니다.")
    return int(m.group(1)), int(m.group(2))


def is_allowed_url(url: str) -> bool:
    if not url:
        return False
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    return host in ALLOWED_HOSTS


def save_debug(page, name="debug"):
    try:
        screenshot_path = DEBUG_DIR / f"{name}.png"
        html_path = DEBUG_DIR / f"{name}.html"

        page.screenshot(path=str(screenshot_path), full_page=True)
        html_path.write_text(page.content(), encoding="utf-8")

        print(f"[디버그 저장] screenshot={screenshot_path}")
        print(f"[디버그 저장] html={html_path}")
    except Exception as e:
        print(f"[디버그 저장 실패] {e}")


def handle_new_page(new_page):
    try:
        url = new_page.url or ""
        print(f"[새 페이지 감지] {url}")

        if url in ("", "about:blank"):
            print("[유지] 초기 빈 페이지는 닫지 않습니다.")
            return

        try:
            new_page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

        url = new_page.url or ""
        print(f"[새 페이지 최종 URL] {url}")

        if not is_allowed_url(url):
            print(f"[차단/닫기] 허용되지 않은 페이지라 닫습니다: {url}")
            try:
                new_page.close()
            except Exception:
                pass

    except Exception as e:
        print(f"[handle_new_page 오류] {e}")


def ensure_main_page(page):
    try:
        current = page.url or ""
        if current and not is_allowed_url(current):
            print(f"[복귀] 허용되지 않은 URL 감지: {current}")
            page.goto(TARGET_MAIN_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
    except Exception as e:
        print(f"[ensure_main_page 오류] {e}")


def click_by_text(page, text, exact=False, timeout=7000):
    locator = page.get_by_text(text, exact=exact)
    locator.first.wait_for(timeout=timeout)
    locator.first.scroll_into_view_if_needed()
    locator.first.click(timeout=3000)
    page.wait_for_timeout(1200)


def click_bottom_nav_mypt(page):
    try:
        btn = page.locator("a.a1[href*='mypt1.php'] span.t1")
        btn.first.wait_for(timeout=5000)
        btn.first.click(timeout=3000)
        page.wait_for_timeout(1500)
        print("[성공] 마이PT 클릭")
        return True
    except Exception as e:
        print(f"[오류] 마이PT 클릭 실패: {e}")
        save_debug(page, "mypt_click_fail")
        return False


def click_bottom_nav_study(page):
    try:
        btn = page.locator("li.m.study a.a1").first
        btn.wait_for(state="attached", timeout=5000)
        btn.click(timeout=3000)
        page.wait_for_timeout(1500)
        print("[성공] 하단 공부하기 클릭")
        return True
    except Exception as e:
        print(f"[오류] 하단 공부하기 클릭 실패: {e}")
        save_debug(page, "bottom_study_click_fail")
        return False


def handle_resume_popup(page):
    print("[진입] 이어서 보기 팝업 확인 중...")

    try:
        page.wait_for_timeout(1000)
        btns = page.locator("div.cp1write2 button.m-init1:visible")
        count = btns.count()

        if count == 0:
            print("[정보] 이어보기 팝업 없음 - 바로 문제 진입 케이스")
            return False

        btn = btns.first
        btn.click(timeout=3000, force=True)
        page.wait_for_timeout(1500)
        print("[성공] '1번부터 보기' 클릭")
        return True

    except Exception as e:
        print(f"[오류] 팝업 클릭 실패: {e}")
        save_debug(page, "resume_popup_fail")
        return False


def get_subject_targets(page, subject_name, subtype_name=None):
    """
    반환 규칙
    - 하위 카드가 없으면: 기존 방식용 target 1개 반환
    - 하위 카드가 있으면:
      - subtype_name 없으면 하위 카드 전부 반환(위에서 아래 순서)
      - subtype_name 있으면 해당 문자열 포함하는 하위 카드만 반환
    """
    results = []

    try:
        cards = page.locator("div.cp1flist2 ul.lst1 > li.li1")
        count = cards.count()

        for i in range(count):
            card = cards.nth(i)

            try:
                title = (card.locator(":scope > span.t1").first.text_content() or "").strip()
                title = re.sub(r"\s+", " ", title)
            except Exception:
                title = ""

            if subject_name not in title:
                continue

            sub_cards = card.locator(":scope ul.lst2 > li.li2")
            sub_count = sub_cards.count()

            # 하위 카드 없음 -> 기존 로직 유지
            if sub_count == 0:
                return [{
                    "subject_name": title,
                    "sub_title": None,
                    "card_index": i,
                    "sub_index": None,
                    "has_subcards": False,
                }]

            # 하위 카드 있음
            for j in range(sub_count):
                sub = sub_cards.nth(j)

                try:
                    sub_title = (sub.locator("span.t1").first.text_content() or "").strip()
                    sub_title = re.sub(r"\s+", " ", sub_title)
                except Exception:
                    sub_title = ""

                if subtype_name and subtype_name not in sub_title:
                    continue

                results.append({
                    "subject_name": title,
                    "sub_title": sub_title,
                    "card_index": i,
                    "sub_index": j,
                    "has_subcards": True,
                })

            return results

    except Exception as e:
        print(f"[오류] 과목 실행 대상 조회 실패: {e}")
        save_debug(page, f"subject_target_lookup_fail_{norm_id_text(subject_name)}")

    return results


def click_subject_target(page, target):
    """
    target 기준으로 실제 클릭
    - 하위 카드 없으면 기존 방식
    - 하위 카드 있으면 해당 하위 카드 안에서
      이어하기 우선 -> 공부하기 -> fallback a.b2
    """
    try:
        cards = page.locator("div.cp1flist2 ul.lst1 > li.li1")
        card = cards.nth(target["card_index"])

        # 하위 카드 없는 기존 구조
        if target["sub_index"] is None:
            btn = card.locator("a.b2").first
            btn.wait_for(state="attached", timeout=5000)

            btn_text = (btn.text_content() or "").strip()
            btn_text = re.sub(r"\s+", " ", btn_text)
            print(f"[디버그] '{target['subject_name']}' 버튼 문구: {btn_text}")

            btn.click(timeout=3000, force=True)
            page.wait_for_timeout(1500)
            print(f"[성공] 상위 과목 클릭: {target['subject_name']}")
            handle_resume_popup(page)
            return True

        # 하위 카드 있는 구조
        sub = card.locator(":scope ul.lst2 > li.li2").nth(target["sub_index"])

        try:
            sub_title = (sub.locator("span.t1").first.text_content() or "").strip()
            sub_title = re.sub(r"\s+", " ", sub_title)
        except Exception:
            sub_title = target.get("sub_title") or ""

        btn = None

        try:
            candidate = sub.locator("a.b2:has-text('해설보며 이어하기')").first
            if candidate.count() > 0 and candidate.is_visible():
                btn = candidate
        except Exception:
            pass

        if btn is None:
            try:
                candidate = sub.locator("a.b2:has-text('해설보며 공부하기')").first
                if candidate.count() > 0 and candidate.is_visible():
                    btn = candidate
            except Exception:
                pass

        if btn is None:
            btn = sub.locator("a.b2").first

        btn.wait_for(state="attached", timeout=5000)

        btn_text = (btn.text_content() or "").strip()
        btn_text = re.sub(r"\s+", " ", btn_text)
        print(f"[디버그] 하위 카드 '{sub_title}' 버튼 문구: {btn_text}")

        btn.click(timeout=3000, force=True)
        page.wait_for_timeout(1500)
        print(f"[성공] 하위 카드 클릭: {sub_title}")
        handle_resume_popup(page)
        return True

    except Exception as e:
        print(f"[오류] 대상 클릭 실패: {e}")
        save_debug(page, f"subject_target_click_fail_{norm_id_text(target.get('subject_name', 'unknown'))}")
        return False


def get_bottom_sheet_container_box(page):
    try:
        container = page.locator("div.container").first
        if container.count() == 0:
            return None
        return container.bounding_box()
    except Exception:
        return None
    
    
def is_bottom_sheet_low_enough(page):
    """
    실제 축소 상태 판정:
    1) cp1answer1choice1 에 off 클래스가 붙었는지
    2) 내부 cont fscroll1-xy 높이가 0에 가까운지
    """
    try:
        root = page.locator("div.cp1answer1choice1").first
        if root.count() == 0:
            print("[정보] 하단 시트 루트 없음")
            return True

        class_attr = root.get_attribute("class") or ""
        is_off = "off" in class_attr.split()

        cont = root.locator("div.cont.fscroll1-xy").first
        cont_box = None
        cont_height = None

        if cont.count() > 0:
            try:
                cont_box = cont.bounding_box()
                cont_height = 0 if not cont_box else cont_box["height"]
            except Exception:
                cont_height = None

        low_enough = bool(is_off) or (cont_height is not None and cont_height <= 5)

        print(
            f"[디버그] 축소 판정 class={class_attr}, "
            f"is_off={is_off}, cont_height={cont_height}, low_enough={low_enough}"
        )

        return low_enough

    except Exception as e:
        print(f"[하단 시트 위치 판정 오류] {e}")
        return False
    
    
# def ensure_bottom_sheet_collapsed(page, max_clicks=5):
#     """
#     해설 캡처 전용:
#     하단 시트가 실제로 내려간 상태가 될 때까지 클릭
#     """
#     try:
#         handle = page.locator("a.b1.handlebar").first

#         if handle.count() == 0:
#             print("[정보] 하단 시트 핸들바 없음")
#             return False

#         handle.wait_for(state="attached", timeout=3000)

#         if is_bottom_sheet_low_enough(page):
#             print("[정보] 하단 시트 이미 축소 상태")
#             return True

#         prev_y = None

#         for i in range(max_clicks):
#             print(f"[디버그] 하단 시트 축소 시도 {i+1}/{max_clicks}")

#             try:
#                 cbox_before = get_bottom_sheet_container_box(page)
#                 before_y = cbox_before["y"] if cbox_before else None
#             except Exception:
#                 before_y = None

#             try:
#                 handle.click(force=True)
#             except Exception as e:
#                 print(f"[경고] 축소 버튼 클릭 실패: {e}")

#             page.wait_for_timeout(900)

#             if is_bottom_sheet_low_enough(page):
#                 print("[성공] 하단 시트 축소 확인 완료")
#                 return True

#             try:
#                 cbox_after = get_bottom_sheet_container_box(page)
#                 after_y = cbox_after["y"] if cbox_after else None
#             except Exception:
#                 after_y = None

#             if before_y is not None and after_y is not None:
#                 print(f"[디버그] container y: {before_y} -> {after_y}")

#             if prev_y is not None and after_y is not None and abs(after_y - prev_y) < 3:
#                 print("[경고] 축소 클릭 후 위치 변화 거의 없음")
#             prev_y = after_y

#         print("[경고] 하단 시트를 충분히 축소하지 못함")
#         return False

#     except Exception as e:
#         print(f"[하단 시트 축소 오류] {e}")
#         return False
    

def ensure_bottom_sheet_collapsed(page, max_clicks=5):
    """
    하단 시트를 실제 off 상태 또는 cont height 0 상태가 될 때까지 축소
    """
    try:
        btn = page.locator("a.b1.handlebar").first

        if btn.count() == 0:
            print("[정보] 하단 시트 핸들바 없음")
            return False

        btn.wait_for(state="attached", timeout=3000)

        if is_bottom_sheet_low_enough(page):
            print("[정보] 하단 시트 이미 축소 상태")
            return True

        for i in range(max_clicks):
            print(f"[디버그] 하단 시트 축소 시도 {i+1}/{max_clicks}")

            try:
                btn.click(force=True)
            except Exception as e:
                print(f"[경고] 축소 버튼 클릭 실패: {e}")

            page.wait_for_timeout(1000)

            if is_bottom_sheet_low_enough(page):
                print("[성공] 하단 시트 축소 확인 완료")
                return True

        print("[경고] 하단 시트를 충분히 축소하지 못함")
        return False

    except Exception as e:
        print(f"[하단 시트 오류] {e}")
        return False


def has_any_choice_image(page):
    """
    현재 화면 상태와 무관하게 DOM 안에 선지 이미지가 있는지 확인
    """
    try:
        return page.locator("ol.lst1 li.li1 img").count() > 0
    except Exception:
        return False


def first_four_choices_visible(page):
    try:
        choices = page.locator("ol.lst1 li.li1 span.t1t1")
        count = choices.count()
        if count < 4:
            return False

        for idx in range(4):
            if not choices.nth(idx).is_visible():
                return False
        return True
    except Exception:
        return False


def ensure_bottom_sheet_expanded_from_collapsed(page, max_clicks=4):
    """
    확장 판정은 애매한 기본 상태를 믿지 않고,
    1) 먼저 축소 상태를 맞춘 뒤
    2) 버튼을 한 번 더 눌러
    3) 1~4번 선지가 모두 visible인지 확인
    """
    try:
        handle = page.locator("a.b1.handlebar").first
        if handle.count() == 0:
            print("[정보] 하단 시트 핸들바 없음")
            return False

        handle.wait_for(state="attached", timeout=3000)

        collapsed = ensure_bottom_sheet_collapsed(page, max_clicks=max_clicks)
        page.wait_for_timeout(700)

        if not collapsed or not is_bottom_sheet_low_enough(page):
            print("[경고] 확장 전 축소 기준 상태 확보 실패")
            return False

        print("[디버그] 축소 상태 확인 후 확장 시도")

        try:
            handle.click(force=True)
        except Exception as e:
            print(f"[경고] 확장 버튼 클릭 실패: {e}")
            return False

        page.wait_for_timeout(900)

        if first_four_choices_visible(page):
            print("[성공] 축소 상태에서 한 번 더 눌러 1~4번 선지 visible 확인")
            return True

        print("[경고] 확장 후에도 1~4번 선지가 모두 보이지 않음")
        return False

    except Exception as e:
        print(f"[하단 시트 확장 오류] {e}")
        return False
    

def wait_until_explanation_ready(page, timeout=15000):
    try:
        body = get_explanation_body_locator(page)
        body.wait_for(state="attached", timeout=timeout)

        max_try = max(1, timeout // 500)

        for _ in range(max_try):
            try:
                text = (body.inner_text() or "").strip()
                if text and "비기봇에게 문의중" not in text and len(text) >= 20:
                    print("[성공] 비기봇 해설 본문 로딩 완료")
                    return True
            except Exception:
                pass

            page.wait_for_timeout(500)

        print("[경고] 비기봇 해설 본문 로딩 대기 시간 초과")
        save_debug(page, "wait_until_explanation_ready_timeout")
        return False

    except Exception as e:
        print(f"[경고] 비기봇 로딩 대기 실패: {e}")
        save_debug(page, "wait_until_explanation_ready_fail")
        return False


def set_page_zoom(page, zoom: float):
    try:
        page.evaluate(
            """(z) => { document.body.style.zoom = String(z); }""",
            zoom
        )
        page.wait_for_timeout(300)
        return True
    except Exception as e:
        print(f"[줌 설정 실패] {e}")
        return False


def explanation_fits_in_view(page, t1, viewport, bottom_margin=40, handle_overlap_guard=20):
    """
    현재 배율/현재 위치 기준으로 해설 전체가 안전 영역 안에 한 번에 들어오는지 판정
    handle_overlap_guard:
      하단 겹침 위험영역(px). fits_now / fits_after_zoom 에서 다르게 줄 수 있음.
    """
    try:
        box = t1.bounding_box()
        if not box:
            return False, None

        container_top = viewport["height"]
        try:
            container = page.locator("div.container").first
            if container.count() > 0:
                cbox = container.bounding_box()
                if cbox:
                    container_top = cbox["y"]
        except Exception:
            pass

        safe_bottom = min(container_top, viewport["height"] - bottom_margin) - handle_overlap_guard

        visible_top = max(box["y"], 0)
        visible_bottom = min(box["y"] + box["height"], safe_bottom)

        visible_start_in_t1 = max(0, visible_top - box["y"])
        visible_end_in_t1 = max(0, visible_bottom - box["y"])
        total_height = box["height"]

        hidden_bottom_px = total_height - visible_end_in_t1
        fits = visible_start_in_t1 <= 10 and hidden_bottom_px <= 5

        print(
            f"[디버그] fits={fits}, guard={handle_overlap_guard}, "
            f"hidden_bottom_px={hidden_bottom_px}, "
            f"safe_bottom={safe_bottom}, "
            f"visible_start={visible_start_in_t1}, "
            f"visible_end={visible_end_in_t1}, "
            f"total_height={total_height}"
        )

        return fits, {
            "box": box,
            "safe_bottom": safe_bottom,
            "visible_top": visible_top,
            "visible_bottom": visible_bottom,
            "visible_start_in_t1": visible_start_in_t1,
            "visible_end_in_t1": visible_end_in_t1,
            "total_height": total_height,
        }

    except Exception as e:
        print(f"[한 화면 적합 여부 판정 실패] {e}")
        return False, None


def element_fits_above_container(page, locator, viewport, bottom_margin=40, handle_overlap_guard=25):
    try:
        box = locator.bounding_box()
        if not box:
            return False, None

        container_top = viewport["height"]
        container = page.locator("div.container").first
        if container.count() > 0:
            cbox = container.bounding_box()
            if cbox:
                container_top = cbox["y"]

        safe_bottom = min(container_top, viewport["height"] - bottom_margin) - handle_overlap_guard

        hidden_bottom_px = (box["y"] + box["height"]) - safe_bottom
        fits = box["y"] >= 0 and hidden_bottom_px <= 5

        print(
            f"[디버그] 이미지 fits={fits}, "
            f"hidden_bottom_px={hidden_bottom_px}, "
            f"safe_bottom={safe_bottom}, "
            f"img_bottom={box['y'] + box['height']}"
        )

        return fits, {
            "box": box,
            "safe_bottom": safe_bottom,
        }

    except Exception as e:
        print(f"[이미지 적합 여부 판정 실패] {e}")
        return False, None


def prepare_element_capture_above_container(page, locator, top_margin=80):
    viewport = page.viewport_size
    if not viewport:
        return False

    box = locator.bounding_box()
    if not box:
        return False

    page.mouse.wheel(0, int(box["y"] - top_margin))
    page.wait_for_timeout(500)

    fits, info = element_fits_above_container(
        page,
        locator,
        viewport,
        bottom_margin=40,
        handle_overlap_guard=25
    )

    if fits:
        return True

    print("[정보] 이미지가 선지 container와 겹침 가능성 있음 -> 하단 시트 축소 시도")

    collapsed = ensure_bottom_sheet_collapsed(page, max_clicks=5)
    page.wait_for_timeout(700)

    if collapsed and is_bottom_sheet_low_enough(page):
        box = locator.bounding_box()
        if box:
            page.mouse.wheel(0, int(box["y"] - top_margin))
            page.wait_for_timeout(500)

        fits, info = element_fits_above_container(
            page,
            locator,
            viewport,
            bottom_margin=40,
            handle_overlap_guard=25
        )

        if fits:
            return True

    print("[정보] 하단 시트 축소 후에도 이미지가 안 들어옴 -> 0.85 → 0.8 배율 시도")

    for zoom in [0.85, 0.8]:
        if not set_page_zoom(page, zoom):
            continue

        page.wait_for_timeout(500)

        recollapsed = ensure_bottom_sheet_collapsed(page, max_clicks=5)
        page.wait_for_timeout(700)

        if not recollapsed or not is_bottom_sheet_low_enough(page):
            continue

        box = locator.bounding_box()
        if box:
            page.mouse.wheel(0, int(box["y"] - top_margin))
            page.wait_for_timeout(500)

        fits, info = element_fits_above_container(
            page,
            locator,
            viewport,
            bottom_margin=40,
            handle_overlap_guard=60
        )

        if fits:
            print(f"[성공] {zoom} 배율에서 이미지가 선지 container와 겹치지 않음")
            return True

    print("[경고] 이미지가 축소 후에도 한 화면에 안전하게 들어오지 않음")
    return False


def capture_explanation_images(page, question_id):
    saved_paths = []
    applied_zoom = 1.0

    meta = {
        "attempted": True,
        "zoom_applied": False,
        "fits_in_single_before_zoom": None,
        "fits_in_single_after_zoom": None,
        "needs_manual_review": False,
        "capture_mode": "not_started",   # single / too_long_after_zoom / skipped / failed / not_needed
        "image_count": 0,
    }

    try:
        wait_until_explanation_ready(page)
        page.wait_for_timeout(500)

        t1 = get_explanation_body_locator(page)
        t1.wait_for(state="visible", timeout=5000)

        viewport = page.viewport_size
        if not viewport:
            print("[오류] viewport 없음")
            meta["capture_mode"] = "failed"
            meta["needs_manual_review"] = True
            return {
                "images": saved_paths,
                "meta": meta,
            }

        top_margin = 80
        bottom_margin = 40
        clip_top_pad = 6

        collapsed = ensure_bottom_sheet_collapsed(page, max_clicks=5)
        page.wait_for_timeout(700)

        if not collapsed or not is_bottom_sheet_low_enough(page):
            print("[경고] 해설 캡처 전 축소 상태 확인 실패 -> 해설 캡처 건너뜀")
            meta["capture_mode"] = "skipped"
            meta["needs_manual_review"] = True
            return {
                "images": saved_paths,
                "meta": meta,
            }

        first_box = t1.bounding_box()
        if not first_box:
            print("[종료] 첫 bounding_box 없음")
            meta["capture_mode"] = "failed"
            meta["needs_manual_review"] = True
            return {
                "images": saved_paths,
                "meta": meta,
            }

        scroll_adjust = first_box["y"] - top_margin
        page.mouse.wheel(0, int(scroll_adjust))
        page.wait_for_timeout(500)

        fits_now, fit_info = explanation_fits_in_view(
            page,
            t1,
            viewport,
            bottom_margin=bottom_margin,
            handle_overlap_guard=25
        )
        
        meta["fits_in_single_before_zoom"] = bool(fits_now)

        if not fits_now:
            print("[정보] 긴 해설 감지 - 0.85 → 0.8 순차 배율 적용 시도")

            zoom_applied_success = False

            for zoom in [0.85, 0.8]:

                print(f"[디버그] 배율 시도: {zoom}")

                if not set_page_zoom(page, zoom):
                    continue

                applied_zoom = zoom
                meta["zoom_applied"] = True

                page.wait_for_timeout(500)

                # 배율 변경 후 다시 축소 상태 재확인
                recollapsed_after_zoom = ensure_bottom_sheet_collapsed(
                    page,
                    max_clicks=5
                )
                page.wait_for_timeout(700)

                if not recollapsed_after_zoom or not is_bottom_sheet_low_enough(page):
                    print(f"[경고] {zoom} 적용 후 축소 상태 확인 실패")
                    continue

                # 배율 적용 후 해설 시작 위치 재정렬
                zoomed_box = t1.bounding_box()
                if zoomed_box:
                    scroll_adjust = zoomed_box["y"] - top_margin
                    page.mouse.wheel(0, int(scroll_adjust))
                    page.wait_for_timeout(500)

                # 다시 한 화면 적합 여부 검사
                fits_after_zoom, fit_info = explanation_fits_in_view(
                    page,
                    t1,
                    viewport,
                    bottom_margin=bottom_margin,
                    handle_overlap_guard=60
                )

                bottom_guard_px = 0

                if fits_after_zoom and fit_info:
                    remaining_margin = fit_info["safe_bottom"] - (
                        fit_info["box"]["y"] + fit_info["total_height"]
                    )
                    print(f"[디버그] remaining_margin={remaining_margin}")

                    if remaining_margin < bottom_guard_px:
                        fits_after_zoom = False
                        print("[정보] 해설 하단 여유 부족 -> 더 작은 배율 시도")

                meta["fits_in_single_after_zoom"] = bool(fits_after_zoom)

                if fits_after_zoom:
                    print(f"[성공] {zoom} 배율에서 해설이 한 화면에 들어옴")
                    zoom_applied_success = True
                    break

            if not zoom_applied_success:
                print("[정보] 0.8까지 시도 후에도 한 화면에 안 들어옴")
                meta["capture_mode"] = "too_long_after_zoom"
                meta["needs_manual_review"] = True
                meta["image_count"] = 0

                return {
                    "images": saved_paths,
                    "meta": meta,
                }

        final_guard = 60 if meta["zoom_applied"] else 25

        fits_single, fit_info = explanation_fits_in_view(
            page,
            t1,
            viewport,
            bottom_margin=bottom_margin,
            handle_overlap_guard=final_guard
        )

        if not fits_single or not fit_info:
            print("[경고] 단일 캡처 조건 미충족 -> 사람 확인 필요")
            meta["capture_mode"] = "too_long_after_zoom" if meta["zoom_applied"] else "failed"
            meta["needs_manual_review"] = True
            return {
                "images": saved_paths,
                "meta": meta,
            }

        box = fit_info["box"]
        safe_bottom = fit_info["safe_bottom"]

        # 저장은 판정보다 조금 덜 보수적으로
        capture_guard = 25 if meta["zoom_applied"] else 15
        capture_safe_bottom = safe_bottom + (final_guard - capture_guard)

        clip_x = max(box["x"], 0)
        clip_width = min(box["width"], viewport["width"] - clip_x)
        clip_y = max(0, box["y"] - clip_top_pad)
        clip_bottom = min(
            capture_safe_bottom,
            box["y"] + box["height"]
        )
        clip_height = clip_bottom - clip_y

        if clip_width <= 0 or clip_height <= 50:
            print("[경고] 단일 캡처 clip 크기 부족 -> 사람 확인 필요")
            meta["capture_mode"] = "failed"
            meta["needs_manual_review"] = True
            return {
                "images": saved_paths,
                "meta": meta,
            }

        filepath = IMG_DIR / f"{question_id}_explanation_1.png"
        page.screenshot(
            path=str(filepath),
            clip={
                "x": clip_x,
                "y": clip_y,
                "width": clip_width,
                "height": clip_height,
            },
        )
        saved_paths.append(str(filepath))
        print(f"[캡처] {filepath}")
        print("[완료] 해설이 한 화면에 모두 들어와 1장만 저장")

        meta["capture_mode"] = "single"
        meta["image_count"] = 1

        return {
            "images": saved_paths,
            "meta": meta,
        }

    except Exception as e:
        print(f"[해설 캡처 실패] {e}")
        save_debug(page, f"explanation_capture_fail_{question_id}")

        meta["capture_mode"] = "failed"
        meta["needs_manual_review"] = True
        meta["image_count"] = len(saved_paths)

        return {
            "images": saved_paths,
            "meta": meta,
        }



            
def close_main_popup_today(page):
    """
    메인 진입 시 뜨는 이벤트 팝업에서
    '오늘은 그만 보기'를 우선 클릭한다.
    """
    selectors = [
        "a[onclick*='closePop'][onclick*='checked']",
        "a[href^='#pop'][onclick*='checked']",
        "a.b1",
        "a:has(span:has-text('오늘은 그만 보기'))",
        "text=오늘은 그만 보기",
    ]

    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.is_visible(timeout=1500):
                loc.click(force=True, timeout=2000)
                page.wait_for_timeout(700)
                print(f"[팝업 처리] 오늘은 그만 보기 클릭 성공: {selector}")
                return True
        except Exception:
            pass

    print("[팝업 처리] 오늘은 그만 보기 버튼을 찾지 못함")
    return False


def click_hamburger_menu(page):
    try:
        btn = page.locator("a.b1.toggle")
        btn.first.wait_for(state="attached", timeout=5000)
        btn.first.click(timeout=3000)
        page.wait_for_timeout(1000)
        print("[성공] 햄버거 메뉴 클릭")
        return True
    except Exception as e:
        print(f"[오류] 햄버거 클릭 실패: {e}")
        save_debug(page, "hamburger_click_fail")
        return False


def click_login_entry(page) -> bool:
    try:
        btn = page.locator("a.a1[href*='login1.php']")
        btn.first.click(timeout=3000)
        page.wait_for_timeout(1500)
        print("[성공] 로그인 클릭")
        return True
    except Exception as e:
        print(f"[실패] 로그인 클릭 실패: {e}")
        save_debug(page, "login_entry_fail")
        return False


def submit_login(page) -> bool:
    selectors = [
        "button[type='submit']",
        "input[type='submit']",
        "button",
    ]

    for sel in selectors:
        try:
            items = page.locator(sel)
            count = items.count()

            for i in range(count):
                el = items.nth(i)
                txt = safe_text(el)

                if "로그인" in txt or "LOGIN" in txt or "Login" in txt:
                    el.click(timeout=3000)
                    page.wait_for_timeout(3000)
                    print(f"[성공] 로그인 제출: {sel}")
                    return True
        except Exception:
            continue

    save_debug(page, "login_submit_failed")
    return False


def login(page, user_id, password):
    page.goto(TARGET_MAIN_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    ensure_main_page(page)
    save_debug(page, "before_login_attempt")

    close_main_popup_today(page)
    page.wait_for_timeout(800)

    if not click_hamburger_menu(page):
        raise RuntimeError("햄버거 메뉴를 찾지 못했습니다.")

    save_debug(page, "after_hamburger_click")

    if not click_login_entry(page):
        raise RuntimeError("로그인 버튼 클릭에 실패했습니다.")

    save_debug(page, "after_login_entry_click")

    try:
        page.locator("input").nth(0).wait_for(state="visible", timeout=5000)
        page.locator("input").nth(1).wait_for(state="visible", timeout=5000)
    except Exception:
        save_debug(page, "login_inputs_not_found")
        raise RuntimeError("로그인 입력창을 찾지 못했습니다.")

    try:
        page.locator("input").nth(0).fill(user_id)
        page.locator("input").nth(1).fill(password)
        print("[성공] 로그인 정보 입력 완료")
    except Exception:
        save_debug(page, "login_fill_failed")
        raise RuntimeError("로그인 입력값 입력에 실패했습니다.")

    if not submit_login(page):
        raise RuntimeError("로그인 제출에 실패했습니다.")

    page.wait_for_timeout(5000)
    page.goto(TARGET_MAIN_URL, wait_until="networkidle")
    page.wait_for_timeout(3000)

    page.locator("a.a1[href*='mypt1.php'] span.t1").first.wait_for(timeout=10000)
    ensure_main_page(page)
    save_debug(page, "after_login_main_reload")


def extract_keywords(page):
    keywords = []

    try:
        wait_until_explanation_ready(page)

        for sel in EXPLANATION_KEYWORD_SELECTORS:
            items = page.locator(sel)
            count = items.count()

            if count == 0:
                continue

            for i in range(count):
                raw = items.nth(i).text_content() or ""
                txt = re.sub(r"\s+", " ", raw).strip()

                if not txt:
                    continue

                txt = txt.lstrip("#").strip()

                if txt and txt not in keywords:
                    keywords.append(txt)

            if keywords:
                break

    except Exception as e:
        print(f"[keywords 추출 오류] {e}")
        save_debug(page, "extract_keywords_fail")

    return keywords


def extract_section_tags(page):
    tags = []

    try:
        container = page.locator("div.cp1question1 div.w1").first
        container.wait_for(state="attached", timeout=5000)

        items = container.locator("span.g1")
        count = items.count()

        for i in range(count):
            raw = items.nth(i).text_content() or ""
            txt = re.sub(r"\s+", " ", raw).strip()
            if txt:
                tags.append(txt)

    except Exception as e:
        print(f"[section_tags 추출 오류] {e}")
        save_debug(page, "extract_section_tags_fail")

    return tags


def get_image_name_from_li(li, question_id, num):
    """
    선지 이미지의 원본 파일명 추출
    우선순위:
    1) a href 의 img 파라미터
    2) img src 파일명
    3) fallback
    """
    try:
        img = li.locator("img").first
        if img.count() > 0:
            original_name = get_original_image_name(img)
            if original_name:
                base_name = re.sub(r"\.\w+$", ".png", original_name)
                base_name = re.sub(r"[^\w가-힣\.]+", "_", base_name)
                return base_name
    except Exception as e:
        print(f"[선지 원본 파일명 추출 오류] num={num}, err={e}")

    return f"{question_id}_choice_{num}.png"


def get_original_image_name(img_locator):
    """
    이미지의 원본 파일명을 최대한 보존해서 추출
    우선순위:
    1) 부모 a 태그 href의 ?img= 파라미터
    2) img src 파일명
    3) 실패 시 빈 문자열
    """
    try:
        parent_a = img_locator.locator("xpath=ancestor::a[1]").first

        if parent_a.count() > 0:
            href = parent_a.get_attribute("href") or ""
            if href:
                parsed = urlparse(href)
                qs = parse_qs(parsed.query)
                img_param = qs.get("img", [])
                if img_param and img_param[0].strip():
                    return img_param[0].strip()
    except Exception:
        pass

    try:
        src = img_locator.get_attribute("src") or ""
        if src:
            return Path(urlparse(src).path).name
    except Exception:
        pass

    return ""


def capture_question_and_choice_images(page, question_id, recollapse_after_choice_capture=False):
    image_elements = []
    expanded_for_choice_capture = False

    question_image_capture_meta = {
        "attempted": True,
        "needs_manual_review": False,
        "capture_mode": "not_needed",
        "image_count": 0,
        "failed_indexes": [],
    }
    
    # 문제 이미지
    try:
        q_items = page.locator("div.tg1 img")
        q_count = q_items.count()

        if q_count > 0:
            question_image_capture_meta["capture_mode"] = "single"
            
        for i in range(q_count):
            img = q_items.nth(i)

            try:
                src = img.get_attribute("src") or ""
                alt = img.get_attribute("alt") or ""
                original_name = get_original_image_name(img)

                if original_name:
                    base_name = re.sub(r"\.\w+$", ".png", original_name)
                    base_name = re.sub(r"[^\w가-힣\.]+", "_", base_name)
                else:
                    base_name = f"{question_id}_question_img_{i+1}.png"

                filepath = IMG_DIR / base_name

                if filepath.exists():
                    stem = Path(base_name).stem
                    suffix = Path(base_name).suffix or ".png"
                    filename = f"{stem}_{i+1}{suffix}"
                    filepath = IMG_DIR / filename

                prepared = prepare_element_capture_above_container(page, img, top_margin=80)

                if not prepared:
                    print(f"[경고] 문제 이미지가 선지 container와 겹칠 수 있어 저장 건너뜀: idx={i}")
                    question_image_capture_meta["needs_manual_review"] = True
                    question_image_capture_meta["capture_mode"] = "overlap_or_too_long_after_zoom"
                    question_image_capture_meta["failed_indexes"].append(i + 1)
                    continue

                img.screenshot(path=str(filepath))
                question_image_capture_meta["image_count"] += 1

                image_elements.append({
                    "type": "screenshot",
                    "location": "question",
                    "caption_or_near_text": sanitize_text(alt),
                    "ocr_or_extracted_text": original_name or (Path(urlparse(src).path).name if src else Path(filepath).name),
                    "saved_path": str(filepath)
                })

            except Exception as e:
                print(f"[문제 이미지 저장 실패] idx={i}, err={e}")
                question_image_capture_meta["needs_manual_review"] = True
                question_image_capture_meta["capture_mode"] = "question_image_capture_failed"
                question_image_capture_meta["failed_indexes"].append(i + 1)

    except Exception as e:
        print(f"[문제 이미지 탐색 실패] {e}")

    # 선지 이미지
    try:
        items = page.locator("ol.lst1 li.li1")
        count = items.count()

        has_choice_image = has_any_choice_image(page)

        if has_choice_image:
            expanded = ensure_bottom_sheet_expanded_from_collapsed(page, max_clicks=4)
            page.wait_for_timeout(800)

            if not expanded:
                print("[경고] 선지 이미지용 확장 상태를 확인하지 못해 이번 문제의 선지 이미지 캡처를 건너뜁니다.")
                return {
                    "image_elements": image_elements,
                    "question_image_capture_meta": question_image_capture_meta,
                }

            expanded_for_choice_capture = True

        for i in range(count):
            li = items.nth(i)

            num_raw = li.locator("i.t1n").first.text_content() or ""
            num = re.sub(r"\D+", "", num_raw).strip()
            if not num:
                num = str(i + 1)

            imgs = li.locator("img")
            img_count = imgs.count()

            for j in range(img_count):
                img = imgs.nth(j)

                try:
                    if not img.is_visible():
                        print(f"[디버그] 선지 이미지 비가시 상태 skip: num={num}, idx={j}")
                        continue

                    src = img.get_attribute("src") or ""
                    alt = img.get_attribute("alt") or ""
                    original_name = get_original_image_name(img)

                    if original_name:
                        base_name = re.sub(r"\.\w+$", ".png", original_name)
                        base_name = re.sub(r"[^\w가-힣\.]+", "_", base_name)
                    else:
                        base_name = f"{question_id}_choice_{num}.png"

                    filepath = IMG_DIR / base_name

                    if filepath.exists():
                        stem = Path(base_name).stem
                        suffix = Path(base_name).suffix or ".png"
                        filename = f"{stem}_{num}_{j+1}{suffix}"
                        filepath = IMG_DIR / filename

                    img.screenshot(path=str(filepath))

                    image_elements.append({
                        "type": "screenshot",
                        "location": "choice",
                        "caption_or_near_text": f"choice_{num}",
                        "ocr_or_extracted_text": original_name or (Path(urlparse(src).path).name if src else Path(filepath).name),
                        "saved_path": str(filepath)
                    })

                except Exception as e:
                    print(f"[선지 이미지 저장 실패] num={num}, err={e}")

    except Exception as e:
        print(f"[선지 이미지 탐색 실패] {e}")


    finally:
        if expanded_for_choice_capture and recollapse_after_choice_capture:
            try:
                print("[디버그] 해설 이미지 캡처 예정이므로 선지 캡처 후 재축소 시도")
                recollapsed = ensure_bottom_sheet_collapsed(page, max_clicks=5)
                page.wait_for_timeout(800)

                if recollapsed and is_bottom_sheet_low_enough(page):
                    print("[성공] 해설 이미지 캡처 전 하단 시트 재축소 완료")
                else:
                    print("[경고] 해설 이미지 캡처 전 하단 시트 재축소 확인 실패")
            except Exception as e:
                print(f"[경고] 선지 캡처 후 재축소 오류: {e}")

    return {
        "image_elements": image_elements,
        "question_image_capture_meta": question_image_capture_meta,
    }


def detect_images(page, question_id, recollapse_after_choice_capture=False):
    image_elements = []

    capture_result = capture_question_and_choice_images(
        page,
        question_id,
        recollapse_after_choice_capture=recollapse_after_choice_capture
    )

    image_elements.extend(capture_result.get("image_elements", []))
    question_image_capture_meta = capture_result.get("question_image_capture_meta", {})

    saved_choice_nums = set()
    for item in image_elements:
        if item.get("location") == "choice":
            caption = item.get("caption_or_near_text", "")
            m = re.search(r"choice_(\d+)", caption or "")
            if m:
                saved_choice_nums.add(m.group(1))

    try:
        items = page.locator("ol.lst1 li.li1")
        count = items.count()

        for i in range(count):
            li = items.nth(i)

            num_raw = li.locator("i.t1n").first.text_content() or ""
            num = re.sub(r"\D+", "", num_raw).strip()
            if not num:
                num = str(i + 1)

            if num in saved_choice_nums:
                continue

            text_raw = ""
            try:
                text_raw = li.locator("span.t1t1").first.text_content() or ""
            except Exception:
                pass

            text_val = re.sub(r"\s+", " ", text_raw).strip()
            
            # 기존 코드 삭제
            # text_val = re.sub(r"^\d+\.\s*", "", text_val).strip()

            # 선택지 번호가 붙은 경우만 제거
            text_val = re.sub(rf"^{re.escape(num)}[.)]\s+", "", text_val).strip()

            # 텍스트 선지면 이미지 저장 안 함
            if text_val:
                continue

            filename = get_image_name_from_li(li, question_id, num)
            filepath = IMG_DIR / filename

            if filepath.exists():
                stem = Path(filename).stem
                suffix = Path(filename).suffix or ".png"
                filename = f"{stem}_{num}{suffix}"
                filepath = IMG_DIR / filename

            captured = False

            # 1) 선지 영역 안의 img 직접 캡처
            if not captured:
                try:
                    target = li.locator("span.t1t1 img").first
                    if target.count() > 0:
                        target.screenshot(path=str(filepath))
                        captured = True
                except Exception:
                    pass

            # 2) 선지 영역 전체 캡처
            if not captured:
                try:
                    target = li.locator("span.t1t1").first
                    if target.count() > 0:
                        target.screenshot(path=str(filepath))
                        captured = True
                except Exception:
                    pass

            # 3) li 내부 div.t1 캡처
            if not captured:
                try:
                    target = li.locator("div.t1").first
                    if target.count() > 0:
                        target.screenshot(path=str(filepath))
                        captured = True
                except Exception:
                    pass

            # 4) li 전체 캡처
            if not captured:
                try:
                    li.screenshot(path=str(filepath))
                    captured = True
                except Exception:
                    pass

            if captured:
                image_elements.append({
                    "type": "screenshot",
                    "location": "choice",
                    "caption_or_near_text": f"choice_{num}",
                    "ocr_or_extracted_text": Path(filepath).name,
                    "saved_path": str(filepath)
                })
                saved_choice_nums.add(num)
                print(f"[선지 fallback 저장] num={num}, file={filepath}")
            else:
                print(f"[선지 이미지 캡처 실패] num={num} - 저장 대상 못 찾음")
                try:
                    print(f"[디버그] 선지 {num} HTML:")
                    print(li.inner_html())
                except Exception as debug_e:
                    print(f"[디버그] 선지 {num} HTML 출력 실패: {debug_e}")

    except Exception as e:
        print(f"[선지 이미지 탐지 오류] {e}")

    return {
        "image_elements": image_elements,
        "question_image_capture_meta": question_image_capture_meta,
    }


def extract_question_number(page):
    try:
        el = page.locator("div.cp1question1 div.tg1 strong.tt1 span.tt1n").first
        el.wait_for(state="attached", timeout=5000)

        raw = el.text_content() or ""
        num = re.sub(r"\D+", "", raw).strip()

        if num:
            return int(num)

    except Exception:
        pass

    try:
        text = page.locator("text=/\\d+\\s*/\\s*\\d+/").first.inner_text()
        m = re.search(r"(\d+)\s*/\s*(\d+)", text)
        if m:
            return int(m.group(1))
    except Exception:
        pass

    return 1


def extract_body_and_extra(page):
    body = ""
    extra_text = ""

    try:
        root = page.locator("div.cp1question1 div.tg1 strong.tt1 > span.tt1t1").first
        root.wait_for(state="attached", timeout=5000)

        result = root.evaluate("""
            (el) => {
                const directTexts = [];
                const nestedTexts = [];

                for (const node of el.childNodes) {
                    if (node.nodeType === Node.TEXT_NODE) {
                        const txt = (node.textContent || "").replace(/\\s+/g, " ").trim();
                        if (txt) directTexts.push(txt);
                    } else if (
                        node.nodeType === Node.ELEMENT_NODE &&
                        node.matches("span.tt1t1")
                    ) {
                        const txt = (node.textContent || "").replace(/\\s+/g, " ").trim();
                        if (txt) nestedTexts.push(txt);
                    }
                }

                return {
                    body: directTexts.join(" ").trim(),
                    extra_text: nestedTexts.join(" ").trim()
                };
            }
        """)

        body = result.get("body", "").strip()
        extra_text = result.get("extra_text", "").strip()

        print(f"[디버그] body: {repr(body)}")
        print(f"[디버그] extra_text: {repr(extra_text)}")

    except Exception as e:
        print(f"[body/extra_text 추출 오류] {e}")
        save_debug(page, "extract_body_and_extra_fail")

    return body, extra_text


def extract_explanation(page):
    try:
        wait_until_explanation_ready(page)
        page.wait_for_timeout(300)

        el = get_explanation_body_locator(page)
        el.wait_for(state="attached", timeout=5000)

        text = el.inner_text().strip()

        print(f"[디버그] 해설(줄바꿈 유지):\n{text[:300]}")
        return text

    except Exception as e:
        print(f"[해설 추출 오류] {e}")
        save_debug(page, "extract_explanation_fail")
        return ""


def should_capture_explanation(page, text):

    # MathJax 수식 있으면 캡처
    try:
        if page.locator("mjx-container, mjx-math, math").count() > 0:
            print("[판단] MathJax 수식 존재 -> 해설 이미지 캡처")
            return True
    except Exception:
        pass

    # 수식 문자 패턴 있으면 캡처
    if any(token in text for token in ["\\", "$", "*", "=", "{"]):
        return True

    if re.search(r"\w+/\w+", text):
        return True

    # 수식 없으면 캡처 안 함
    return False


def extract_choices(page, question_id, image_elements=None):
    choices = []
    choice_image_map = {}

    if image_elements:
        for item in image_elements:
            if item.get("location") == "choice":
                saved_name = Path(item.get("saved_path", "")).name
                caption = item.get("caption_or_near_text", "")
                m = re.search(r"choice_(\d+)", caption or "")
                if m:
                    choice_image_map[m.group(1)] = saved_name

    try:
        items = page.locator("ol.lst1 li.li1")
        count = items.count()

        for i in range(count):
            li = items.nth(i)

            num_raw = li.locator("i.t1n").first.text_content() or ""
            num = re.sub(r"\D+", "", num_raw).strip()
            if not num:
                num = str(i + 1)

            text_val = ""
            try:
                text_raw = li.locator("span.t1t1").first.text_content() or ""
                text_val = re.sub(r"\s+", " ", text_raw).strip()
            except Exception:
                text_val = ""

            text_val = re.sub(rf"^{re.escape(num)}[.)]\s+", "", text_val).strip()

            if text_val:
                choices.append(f"{num}. {text_val}")
                continue

            if num in choice_image_map:
                choices.append(f"{num}. [이미지 선지: {choice_image_map[num]}]")
            else:
                filename = get_image_name_from_li(li, question_id, num)
                choices.append(f"{num}. [이미지 선지: {filename}]")

    except Exception as e:
        print(f"[선지 추출 오류] {e}")
        save_debug(page, "extract_choices_fail")

    return choices[:4]


def extract_answer_from_dom(page):
    try:
        correct_item = page.locator("ol.lst1 li.li1.correct").first

        if correct_item.count() == 0:
            correct_item = page.locator("ol.lst1 li.li1.on.correct").first

        if correct_item.count() == 0:
            return ""

        num_text = correct_item.locator("i.t1n").first.text_content() or ""
        num_text = re.sub(r"\D+", "", num_text).strip()

        if num_text:
            print(f"[성공] 정답 추출: {num_text}")
            return num_text

    except Exception as e:
        print(f"[정답 추출 오류] {e}")
        save_debug(page, "answer_dom_fail")

    return ""


def normalize_subject_text(txt: str):
    txt = sanitize_text(txt)
    txt = re.sub(r"\[\d+과목\]\s*", "", txt)
    return txt.strip()


def get_subjects(page, cfg):
    subject_mode = cfg.get("subject_mode", "none")
    subject_name = cfg.get("subject_name")
    subject_start_index = cfg.get("subject_start_index", 1)
    subject_end_index = cfg.get("subject_end_index")

    if subject_mode == "none":
        return ["__single__"]

    if subject_mode == "specific" and subject_name:
        return [subject_name]

    found = []

    cards = page.locator("div.cp1flist2 ul.lst1 > li.li1")
    count = cards.count()

    for i in range(count):
        try:
            title = (cards.nth(i).locator(":scope > span.t1").first.text_content() or "").strip()
            title = normalize_subject_text(title)
            if title and title not in found:
                found.append(title)
        except Exception:
            continue

    print(f"[정제된 과목 목록] {found}")

    if subject_mode == "first":
        return found[:1] if found else []

    if subject_mode == "all":
        if not found:
            return []
        if subject_end_index is None:
            subject_end_index = len(found)

        start_idx = max(subject_start_index - 1, 0)
        end_idx = min(subject_end_index, len(found))
        return found[start_idx:end_idx]

    return found


def is_text_visible(page, text, timeout=2000):
    try:
        loc = page.get_by_text(text, exact=False).first
        loc.wait_for(timeout=timeout)
        return loc.is_visible()
    except Exception:
        return False


def scroll_target_above_bottom_nav(page, locator, extra_margin=170):
    try:
        locator.evaluate("""
            (el) => {
                el.scrollIntoView({ block: 'center', inline: 'nearest' });
            }
        """)
        page.wait_for_timeout(400)

        box = locator.bounding_box()
        viewport = page.viewport_size

        if not box or not viewport:
            return False

        safe_bottom = viewport["height"] - extra_margin
        element_bottom = box["y"] + box["height"]

        if element_bottom > safe_bottom:
            move_up = element_bottom - safe_bottom + 40
            page.mouse.wheel(0, move_up)
            page.wait_for_timeout(300)

        return True

    except Exception as e:
        print(f"[스크롤 보정 실패] {e}")
        return False


def collect_visible_set_cards(page):
    results = []
    cards = page.locator("div.cp1flist1 li.li1 a.a1, div.cp1flist2 li.li1 a.a1")
    count = cards.count()

    for i in range(count):
        try:
            card = cards.nth(i)
            title_el = card.locator("strong.t1").first
            if title_el.count() == 0:
                continue

            title = sanitize_text(title_el.text_content() or "")
            if not title:
                continue

            results.append((i, card, title))
        except Exception:
            continue

    return results


def click_set_card(page, set_name):
    try:
        page.locator("div.cp1flist1 strong.t1, div.cp1flist2 strong.t1").first.wait_for(
            state="attached", timeout=10000
        )

        target_norm = sanitize_text(set_name)
        seen_titles = set()
        prev_last_title = ""
        max_scroll_try = 12

        for attempt in range(max_scroll_try):
            found_cards = collect_visible_set_cards(page)
            print(f"[디버그] 세트 카드 개수(시도 {attempt + 1}): {len(found_cards)}")

            current_titles = []

            for idx, card, title in found_cards:
                current_titles.append(title)
                print(f"[디버그] 세트 카드 제목[{idx}]: {title}")
                seen_titles.add(title)

                if title != target_norm:
                    continue

                href = card.get_attribute("href") or ""
                onclick = card.get_attribute("onclick") or ""
                print(f"[디버그] 클릭 대상 href[{idx}]: {href}")
                print(f"[디버그] 클릭 대상 onclick[{idx}]: {onclick}")

                scroll_target_above_bottom_nav(page, card)
                page.wait_for_timeout(300)

                try:
                    card.click(timeout=3000)
                    page.wait_for_timeout(2000)
                    print(f"[성공] 세트 클릭: {title}")
                    print(f"[디버그] 세트 클릭 후 URL: {page.url}")
                    return True
                except Exception as click_err:
                    print(f"[경고] 직접 클릭 실패: {click_err}")

                if href:
                    try:
                        full_url = urljoin(page.url, href)
                        print(f"[디버그] 직접 이동 URL[{idx}]: {full_url}")
                        page.goto(full_url, wait_until="domcontentloaded")
                        page.wait_for_timeout(2000)
                        print(f"[성공] 세트 직접 이동: {title}")
                        print(f"[디버그] 세트 직접 이동 후 URL: {page.url}")
                        return True
                    except Exception as goto_err:
                        print(f"[경고] href 직접 이동 실패: {goto_err}")

                raise RuntimeError(f"세트 '{title}' 클릭/이동 모두 실패")

            last_title = current_titles[-1] if current_titles else ""

            if last_title and last_title == prev_last_title:
                print("[정보] 추가 스크롤해도 새 세트 카드가 나타나지 않습니다.")
                break
            prev_last_title = last_title

            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(800)

        print(f"[실패] 세트 '{set_name}'를 찾지 못했습니다.")
        print(f"[디버그] 지금까지 본 세트들: {sorted(seen_titles)}")
        save_debug(page, "set_card_not_found_after_scroll")
        return False

    except Exception as e:
        print(f"[오류] 세트 카드 클릭 실패: {e}")
        save_debug(page, "set_card_click_fail")
        return False


def click_course_card(page, course_name):
    try:
        target_norm = sanitize_text(course_name)
        prev_last_title = ""
        max_scroll_try = 10

        for attempt in range(max_scroll_try):
            cards = page.locator("li.li1 a.a1")
            count = cards.count()
            current_titles = []

            for i in range(count):
                try:
                    card = cards.nth(i)
                    title_el = card.locator("strong.t1, span.t1").first
                    if title_el.count() == 0:
                        continue

                        # noqa: unreachable
                    title = title_el.evaluate("""
                        (el) => {
                            const clone = el.cloneNode(true);
                            clone.querySelectorAll('em.em5').forEach(e => e.remove());
                            return (clone.textContent || '').replace(/\\s+/g, ' ').trim();
                        }
                    """)
                    title = sanitize_text(title)

                    if not title:
                        continue

                    current_titles.append(title)
                    print(f"[디버그] 강좌 카드[{i}]: {title}")

                    if title != target_norm:
                        continue

                    scroll_target_above_bottom_nav(page, card)
                    page.wait_for_timeout(300)
                    card.click(timeout=3000)
                    page.wait_for_timeout(2000)
                    print(f"[성공] 강좌 클릭: {title}")
                    return True

                except Exception as inner_e:
                    print(f"[경고] 강좌 카드[{i}] 처리 실패: {inner_e}")
                    continue

            last_title = current_titles[-1] if current_titles else ""
            if last_title and last_title == prev_last_title:
                print("[정보] 추가 스크롤해도 새 강좌 카드가 없습니다.")
                break
            prev_last_title = last_title

            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(800)

        print(f"[실패] 강좌 '{course_name}'를 찾지 못했습니다.")
        save_debug(page, f"course_card_not_found_{norm_id_text(course_name)}")
        return False

    except Exception as e:
        print(f"[오류] 강좌 카드 클릭 실패: {e}")
        save_debug(page, "course_card_click_fail")
        return False


def navigate_to_target(page, cfg):
    ensure_main_page(page)
    save_debug(page, "before_mypt_click")

    if not click_bottom_nav_mypt(page):
        save_debug(page, "mypt_not_found")
        raise RuntimeError("마이PT를 찾지 못했습니다.")
    page.wait_for_timeout(3000)
    save_debug(page, "after_mypt_click")

    course_name = cfg.get("course_name", "")
    if course_name:
        if not click_course_card(page, course_name):
            save_debug(page, "course_not_found")
            raise RuntimeError(f"강좌 '{course_name}'를 찾지 못했습니다.")
        page.wait_for_timeout(2000)
        save_debug(page, "after_course_click")

    if not click_bottom_nav_study(page):
        save_debug(page, "bottom_study_not_found")
        raise RuntimeError("하단 공부하기 버튼을 찾지 못했습니다.")

    page.locator("div.cp1flist1 strong.t1, div.cp1flist2 strong.t1").first.wait_for(
        state="attached", timeout=10000
    )
    page.wait_for_timeout(1000)
    save_debug(page, "after_study_click")

    if not click_set_card(page, cfg["set_name"]):
        save_debug(page, "set_not_found")
        raise RuntimeError(f"세트 '{cfg['set_name']}'를 찾지 못했습니다.")

    page.wait_for_timeout(2000)
    save_debug(page, "after_set_click")

    if cfg.get("exam_round"):
        if not is_text_visible(page, str(cfg["exam_round"]), timeout=5000):
            save_debug(page, "round_not_found")
            raise RuntimeError(f"회차 '{cfg['exam_round']}'를 찾지 못했습니다.")

        click_by_text(page, str(cfg["exam_round"]), exact=False)
        page.wait_for_timeout(2000)
        save_debug(page, "after_round_click")

    subjects = get_subjects(page, cfg)
    print(f"[과목 목록] {subjects}")
    return subjects


def go_next_question(page, current_no):
    old_no = current_no

    try:
        btn = page.locator("a.b1.next.btn-move")

        if btn.count() == 0:
            print("[완료] 마지막 문제까지 도달했습니다. 다음 버튼 없음")
            return None

        btn.first.click(timeout=3000)
        print("[클릭] 다음 문제 버튼 클릭")

        for _ in range(10):
            page.wait_for_timeout(500)
            new_no = extract_question_number(page)

            if new_no != old_no:
                print(f"[성공] 다음 문제 이동: {old_no} -> {new_no}")
                return True

        print("[실패] 클릭했지만 문제 번호 안 바뀜")

    except Exception as e:
        print(f"[오류] 다음 문제 클릭 실패: {e}")
        save_debug(page, "next_click_fail")

    return False


def extract_question(page, course_name, set_name, subject_name, capture_assets=True, sub_title=None):
    question_no = extract_question_number(page)

    qid = make_question_id(
        course_name,
        set_name,
        subject_name,
        question_no,
        sub_title=sub_title
    )

    if not capture_assets:
        return {
            "question_id": qid,
            "course_name": course_name,
            "set_name": set_name,
            "subject_name": subject_name,
            "sub_title": sub_title,
            "question_no": question_no,
            "data": {
                "body": "",
                "extra_text": "",
                "choices": [],
                "answer": "",
                "explanation": "",
                "explanation_images": [],
                "section_tags": [],
                "keywords": [],
                "has_image": False,
                "has_question_image": False,
                "has_choice_image": False,
                "image_elements": [],
                "explanation_capture_meta": {
                    "attempted": False,
                    "zoom_applied": False,
                    "fits_in_single_before_zoom": None,
                    "fits_in_single_after_zoom": None,
                    "needs_manual_review": False,
                    "capture_mode": "not_attempted",
                    "image_count": 0,
                },
                "question_image_capture_meta": {
                    "attempted": False,
                    "needs_manual_review": False,
                    "capture_mode": "not_attempted",
                    "image_count": 0,
                    "failed_indexes": [],
                },
            }
        }

    body, extra_text = extract_body_and_extra(page)
    explanation = extract_explanation(page)
    answer = extract_answer_from_dom(page)
    section_tags = extract_section_tags(page)
    keywords = extract_keywords(page)

    should_capture_expl = should_capture_explanation(page, explanation)

    image_result = detect_images(
        page,
        qid,
        recollapse_after_choice_capture=should_capture_expl
    )

    image_elements = image_result.get("image_elements", [])
    question_image_capture_meta = image_result.get("question_image_capture_meta", {})
    
    choices = extract_choices(page, qid, image_elements)

    explanation_images = []
    explanation_capture_meta = {
        "attempted": False,
        "zoom_applied": False,
        "fits_in_single_before_zoom": None,
        "fits_in_single_after_zoom": None,
        "needs_manual_review": False,
        "capture_mode": "not_needed",
        "image_count": 0,
    }

    if should_capture_expl:
        explanation_capture_result = capture_explanation_images(page, qid)
        explanation_images = explanation_capture_result.get("images", [])
        explanation_capture_meta = explanation_capture_result.get("meta", explanation_capture_meta)

    has_question_image = any(
        img.get("location") == "question"
        for img in image_elements
    )

    has_choice_image = any(
        img.get("location") == "choice"
        for img in image_elements
    )

    return {
        "question_id": qid,
        "course_name": course_name,
        "set_name": set_name,
        "subject_name": subject_name,
        "sub_title": sub_title,
        "question_no": question_no,
        "data": {
            "body": body,
            "extra_text": extra_text,
            "choices": choices,
            "answer": answer,
            "explanation": explanation,
            "explanation_images": explanation_images,
            "explanation_capture_meta": explanation_capture_meta,
            "section_tags": section_tags,
            "keywords": keywords,
            "has_image": len(image_elements) > 0,
            "has_question_image": has_question_image,
            "question_image_capture_meta": question_image_capture_meta,
            "has_choice_image": has_choice_image,
            "image_elements": image_elements
        }
    }

# txt      
def append_manual_review_if_new(q):
    review_items = []

    expl_meta = q["data"].get("explanation_capture_meta", {})
    if expl_meta.get("needs_manual_review"):
        review_items.append(("explanation", expl_meta.get("capture_mode")))

    qimg_meta = q["data"].get("question_image_capture_meta", {})
    if qimg_meta.get("needs_manual_review"):
        review_items.append(("question_image", qimg_meta.get("capture_mode")))

    if not review_items:
        return

    review_path = RAW_DIR / "manual_review_items.txt"
    qid = q["question_id"]

    existing = set()
    if review_path.exists():
        with open(review_path, "r", encoding="utf-8") as rf:
            for line in rf:
                existing.add(line.strip())

    with open(review_path, "a", encoding="utf-8") as rf:
        for item_type, mode in review_items:
            line = f"{qid}\t{item_type}\t{mode}"
            if line not in existing:
                rf.write(line + "\n")
                
                
def main():
    print("[확인] 최신 collect.py 실행 중")
    load_dotenv(ROOT / ".env")
    configs = load_config()

    user_id = os.getenv("DATAEDU_ID")
    password = os.getenv("DATAEDU_PW")
    if not user_id or not password:
        raise RuntimeError(".env에 DATAEDU_ID, DATAEDU_PW가 필요합니다.")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--window-size=900,980"]
        )

        context = browser.new_context(
            viewport={"width": 900, "height": 900}
        )

        page = context.new_page()
        context.on("page", handle_new_page)

        login(page, user_id, password)

        for cfg_idx, cfg in enumerate(configs, start=1):
            try:
                print(f"\n[설정 시작 {cfg_idx}/{len(configs)}] "
                      f"{cfg['course_name']} / {cfg['set_name']}")

                qrange = parse_question_range(cfg["question_range"])

                page.goto(TARGET_MAIN_URL, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                ensure_main_page(page)

                subjects = navigate_to_target(page, cfg)
                save_debug(page, f"set_screen_ready_{cfg_idx}")

                set_screen_url = page.url
                print(f"[정보] 세트 화면 URL: {set_screen_url}")
                print(f"[정보] subjects: {subjects}")

                subtype_name = cfg.get("subtype_name")

                for idx, subject in enumerate(subjects):
                    try:
                        print(f"[과목 시작] cfg={cfg_idx}, idx={idx}, subject={subject}")

                        if idx > 0:
                            page.goto(set_screen_url, wait_until="domcontentloaded")
                            page.wait_for_timeout(2000)
                            save_debug(page, f"back_to_set_screen_{cfg_idx}_{idx}")

                        if qrange is None:
                            start_no, end_no = 1, 9999
                        else:
                            start_no, end_no = qrange

                        if subject not in [None, "__single__", "__FIRST__"]:
                            targets = get_subject_targets(page, subject, subtype_name=subtype_name)

                            if not targets:
                                save_debug(page, f"subject_start_not_found_{cfg_idx}_{norm_id_text(str(subject))}")
                                raise RuntimeError(f"'{subject}' 실행 대상을 찾지 못했습니다.")

                            print(f"[디버그] 실행 대상 수: {len(targets)}")

                            for t_idx, target in enumerate(targets):
                                try:
                                    print(f"[하위 실행 시작] cfg={cfg_idx}, idx={idx}, t_idx={t_idx}, target={target}")

                                    if t_idx > 0:
                                        page.goto(set_screen_url, wait_until="domcontentloaded")
                                        page.wait_for_timeout(2000)
                                        save_debug(page, f"back_to_set_screen_{cfg_idx}_{idx}_{t_idx}")

                                        # 다시 과목 화면의 동일 과목/하위카드 구조를 기준으로 타겟 재계산
                                        targets = get_subject_targets(page, subject, subtype_name=subtype_name)
                                        if t_idx >= len(targets):
                                            raise RuntimeError("재진입 후 실행 대상 인덱스가 맞지 않습니다.")
                                        target = targets[t_idx]

                                    if not click_subject_target(page, target):
                                        save_debug(page, f"subject_target_click_fail_{cfg_idx}_{idx}_{t_idx}")
                                        print(f"[경고] 실행 대상 클릭 실패: {target}")
                                        continue

                                    page.wait_for_timeout(2000)
                                    save_debug(page, f"after_start_question_{cfg_idx}_{idx}_{t_idx}")

                                    while True:
                                        current_question_no = -1
                                        try:
                                            current_question_no = extract_question_number(page)

                                            if current_question_no > end_no:
                                                break

                                            real_subject = subject if isinstance(subject, str) and not subject.startswith("__") else None
                                            capture_assets = start_no <= current_question_no <= end_no

                                            q = extract_question(
                                                page,
                                                cfg["course_name"],
                                                cfg["set_name"],
                                                real_subject,
                                                capture_assets=capture_assets,
                                                sub_title=target["sub_title"] if target["has_subcards"] else None
                                            )
                                        
                                            if start_no <= q["question_no"] <= end_no:
                                                file_path = RAW_DIR / f"{q['question_id']}.json"
                                                with open(file_path, "w", encoding="utf-8") as f:
                                                    json.dump(q, f, ensure_ascii=False, indent=2)
                                                print(f"[RAW 저장] {file_path.name}")


                                            append_manual_review_if_new(q)


                                            if q["question_no"] >= end_no:
                                                break

                                            next_result = go_next_question(page, q["question_no"])

                                            if next_result is None:
                                                print("[완료] 현재 과목/하위 카드의 마지막 문제까지 수집했습니다.")
                                                break

                                            if next_result is False:
                                                print("[종료] 다음 문제 이동 실패")
                                                break

                                        except PlaywrightTimeoutError:
                                            print("[종료] 문제 처리 중 타임아웃")
                                            break
                                        except Exception as e:
                                            print(f"[수집 오류] {e}")
                                            save_debug(page, f"collect_error_cfg_{cfg_idx}_subject_{idx}_target_{t_idx}_q_{current_question_no}")
                                            break

                                except Exception as e:
                                    print(f"[하위 실행 처리 오류] cfg={cfg_idx}, subject={subject}, t_idx={t_idx} / {e}")
                                    save_debug(page, f"subject_target_error_cfg_{cfg_idx}_{idx}_{t_idx}")
                                    continue

                        else:
                            try:
                                click_by_text(page, "해설보며 이어하기", exact=False)
                            except Exception:
                                click_by_text(page, "해설보며 공부하기", exact=False)
                            page.wait_for_timeout(1500)
                            handle_resume_popup(page)

                            page.wait_for_timeout(2000)
                            save_debug(page, f"after_start_question_{cfg_idx}_{idx}")

                            while True:
                                current_question_no = -1
                                try:
                                    current_question_no = extract_question_number(page)

                                    if current_question_no > end_no:
                                        break

                                    real_subject = subject if isinstance(subject, str) and not subject.startswith("__") else None
                                    capture_assets = start_no <= current_question_no <= end_no

                                    q = extract_question(
                                        page,
                                        cfg["course_name"],
                                        cfg["set_name"],
                                        real_subject,
                                        capture_assets=capture_assets,
                                        sub_title=None
                                    )

                                    if start_no <= q["question_no"] <= end_no:
                                        file_path = RAW_DIR / f"{q['question_id']}.json"
                                        with open(file_path, "w", encoding="utf-8") as f:
                                            json.dump(q, f, ensure_ascii=False, indent=2)
                                        print(f"[RAW 저장] {file_path.name}")
                                        
                                    append_manual_review_if_new(q)

                                    if q["question_no"] >= end_no:
                                        break

                                    next_result = go_next_question(page, q["question_no"])

                                    if next_result is None:
                                        print("[완료] 현재 과목의 마지막 문제까지 수집했습니다.")
                                        break

                                    if next_result is False:
                                        print("[종료] 다음 문제 이동 실패")
                                        break

                                except PlaywrightTimeoutError:
                                    print("[종료] 문제 처리 중 타임아웃")
                                    break
                                except Exception as e:
                                    print(f"[수집 오류] {e}")
                                    save_debug(page, f"collect_error_cfg_{cfg_idx}_subject_{idx}_q_{current_question_no}")
                                    break

                    except Exception as e:
                        print(f"[과목 처리 오류] cfg={cfg_idx}, subject={subject} / {e}")
                        save_debug(page, f"subject_error_cfg_{cfg_idx}_{norm_id_text(str(subject))}")
                        continue

            except Exception as e:
                print(f"[설정 처리 오류] cfg={cfg_idx} / {e}")
                save_debug(page, f"config_error_{cfg_idx}")
                continue

        browser.close()


if __name__ == "__main__":
    main()
