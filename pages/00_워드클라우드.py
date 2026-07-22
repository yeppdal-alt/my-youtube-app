import os  # 폰트 파일이 이미 다운로드되어 있는지 확인하기 위해 사용
import random  # 워드클라우드 단어마다 다른 '붉은 톤'을 무작위로 고르기 위해 사용
import re  # 정규식으로 유튜브 링크 파싱 + 댓글에서 단어 뽑아내기에 사용
from collections import Counter  # 단어별 등장 횟수를 세기 위해 사용

import numpy as np  # 하트 모양 마스크(도장)를 수학 공식으로 그리기 위해 사용
import pandas as pd  # 댓글 목록을 표로 예쁘게 보여주기 위해 사용
import plotly.express as px  # 단어 빈도 막대그래프를 그리기 위해 사용
import requests  # YouTube Data API에 HTTP 요청을 보내기 위해 사용
import streamlit as st
from wordcloud import WordCloud  # 워드클라우드 이미지를 만들기 위해 사용

# 워드클라우드에 한글이 깨지지 않게 쓸 나눔고딕 폰트 주소/저장 경로
FONT_URL = (
    "https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/"
    "NanumGothic-Regular.ttf"
)
FONT_PATH = "NanumGothic-Regular.ttf"

# 하트 모양 마스크의 한 변 크기(픽셀). 값이 클수록 해상도가 높아진다.
HEART_MASK_SIZE = 900

# ------------------------------------------------------------------
# 기본 설정
# ------------------------------------------------------------------
st.set_page_config(page_title="유튜브 댓글 분석기", page_icon="💬", layout="centered")

# 예시로 쓸 두 개의 영상 링크
EXAMPLE_1_URL = "https://youtu.be/d95J8yzvjbQ?si=LfL5DLwCL8Pk077r"
EXAMPLE_2_URL = "https://youtu.be/I9vK5EVTt0U?si=NEZ8L7MRuNvrzINa"

# 입력창(text_input)의 값을 코드에서 직접 바꿀 수 있도록
# st.session_state에 기본값을 미리 넣어둔다.
# (text_input을 만들기 "전에" 값을 세팅해야 적용된다)
if "url_input" not in st.session_state:
    st.session_state.url_input = EXAMPLE_1_URL

st.title("💬 유튜브 댓글 분석기")
st.caption("1단계: 영상 링크를 넣으면 좋아요가 많은 순으로 댓글을 가져와요.")

# ------------------------------------------------------------------
# 예시 버튼 두 개 (입력창 위, 나란히 배치)
# ------------------------------------------------------------------
col1, col2 = st.columns(2)
with col1:
    if st.button("예시 1 · 딥마인드 다큐(영어 댓글)", use_container_width=True):
        st.session_state.url_input = EXAMPLE_1_URL
with col2:
    if st.button("예시 2 · 2002 월드컵 추억(한국어 댓글)", use_container_width=True):
        st.session_state.url_input = EXAMPLE_2_URL

# 링크 입력창. key를 "url_input"으로 지정해서 위 버튼들과 값을 공유한다.
url = st.text_input("유튜브 영상 링크를 붙여넣으세요", key="url_input")


# ------------------------------------------------------------------
# 함수 1: 링크에서 영상 ID(11자리 문자열) 뽑아내기
# ------------------------------------------------------------------
def extract_video_id(youtube_url: str):
    """
    유튜브 링크 형태 두 가지를 모두 처리한다.
    - 짧은 링크: https://youtu.be/영상ID?si=...
    - 일반 링크: https://www.youtube.com/watch?v=영상ID&si=...
    si= 같은 뒤에 붙는 부가 값은 무시하고 영상 ID만 뽑는다.
    """
    if not youtube_url:
        return None

    # 유튜브 영상 ID는 영문자, 숫자, -, _ 로 이루어진 11자리 문자열이다.
    patterns = [
        r"youtu\.be/([A-Za-z0-9_-]{11})",              # youtu.be/영상ID
        r"youtube\.com/watch\?.*?v=([A-Za-z0-9_-]{11})",  # youtube.com/watch?v=영상ID
        r"youtube\.com/shorts/([A-Za-z0-9_-]{11})",      # 혹시 모를 쇼츠 링크
    ]
    for pattern in patterns:
        match = re.search(pattern, youtube_url)
        if match:
            return match.group(1)
    return None


# ------------------------------------------------------------------
# 함수 2: YouTube Data API v3로 댓글 가져오기
# ------------------------------------------------------------------
def fetch_comments(video_id: str, api_key: str, max_results: int = 100):
    """
    commentThreads API를 호출해서 최대 100개의 댓글을 받아온다.
    - part=snippet : 댓글 내용/좋아요 수 등 기본 정보만 요청
    - order=relevance : 최신순이 아니라 '인기(좋아요 많은) 순'으로 요청
    실패하면 RuntimeError를 발생시키고, 에러 메시지를 함께 전달한다.
    """
    endpoint = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {
        "part": "snippet",
        "videoId": video_id,
        "maxResults": max_results,
        "order": "relevance",
        "key": api_key,
    }

    response = requests.get(endpoint, params=params, timeout=10)
    data = response.json()

    # API가 에러를 반환한 경우 (잘못된 키, 댓글 사용 중지된 영상 등)
    if response.status_code != 200:
        error_info = data.get("error", {})
        reason = ""
        if error_info.get("errors"):
            reason = error_info["errors"][0].get("reason", "")

        if reason == "commentsDisabled":
            raise RuntimeError("이 영상은 댓글 기능이 꺼져 있어요.")
        elif reason in ("videoNotFound", "notFound"):
            raise RuntimeError("영상을 찾을 수 없어요. 링크를 다시 확인해주세요.")
        else:
            raise RuntimeError(error_info.get("message", "알 수 없는 오류가 발생했어요."))

    # 응답에서 댓글 원문(textOriginal)과 좋아요 수(likeCount)만 추려낸다.
    comments = []
    for item in data.get("items", []):
        snippet = item["snippet"]["topLevelComment"]["snippet"]
        comments.append(
            {
                "댓글": snippet.get("textOriginal", ""),
                "좋아요": snippet.get("likeCount", 0),
            }
        )
    return comments


# ------------------------------------------------------------------
# 함수 3: 댓글 전체에서 단어별 등장 횟수 세기 (한 글자짜리 단어는 제외)
# ------------------------------------------------------------------
def get_word_counter(comments: list) -> Counter:
    """
    댓글들을 전부 이어붙인 뒤, 한글/영문/숫자 덩어리를 '단어'로 뽑아 개수를 센다.
    - 한 글자짜리 단어는 제외한다 (예: "이", "a" 등)
    - 영문은 대소문자를 구분하지 않도록 소문자로 통일한다
    막대그래프(TOP 20)와 워드클라우드가 이 함수 하나를 함께 사용한다.
    """
    all_text = " ".join(c["댓글"] for c in comments)

    # 한글 완성형, 영문자, 숫자로만 이루어진 덩어리를 단어로 취급한다.
    # (이모지, 문장부호, 공백 등은 자동으로 걸러진다)
    raw_words = re.findall(r"[A-Za-z0-9]+|[가-힣]+", all_text)

    words = []
    for w in raw_words:
        w = w.lower()  # 영문 대소문자 통일 (한글은 영향 없음)
        if len(w) >= 2:  # 한 글자짜리 단어는 제외
            words.append(w)

    return Counter(words)


def count_top_words(comments: list, top_n: int = 20):
    """단어 등장 횟수 중 상위 top_n개를 (단어, 횟수) 리스트로 돌려준다."""
    return get_word_counter(comments).most_common(top_n)


# ------------------------------------------------------------------
# 함수 4: 한글 폰트 다운로드 (워드클라우드에서 한글이 깨지지 않도록)
# ------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def download_font():
    """
    나눔고딕 폰트를 인터넷에서 내려받아 로컬에 저장하고 경로를 돌려준다.
    - 이미 받아둔 파일이 있으면 다시 받지 않는다.
    - 다운로드에 실패하면 None을 돌려준다. (호출한 쪽에서 안내 메시지 표시)
    - @st.cache_resource 덕분에 앱이 켜져 있는 동안 한 번만 다운로드한다.
    """
    if os.path.exists(FONT_PATH):
        return FONT_PATH

    try:
        response = requests.get(FONT_URL, timeout=15)
        response.raise_for_status()
        with open(FONT_PATH, "wb") as f:
            f.write(response.content)
        return FONT_PATH
    except requests.exceptions.RequestException:
        return None


# ------------------------------------------------------------------
# 함수 5-1: 하트 모양 마스크(도장) 만들기
# ------------------------------------------------------------------
def make_heart_mask(size: int = HEART_MASK_SIZE):
    """
    하트 커브 수학 공식 (x²+y²-1)³ - x²y³ ≤ 0 을 이용해
    하트 모양 마스크 배열을 만든다.
    - wordcloud 라이브러리 규칙: 마스크 값이 흰색(255)인 곳에는 글자를 그리지 않고,
      그 외(0, 검정)인 곳에만 글자를 채운다.
    - 이미지 좌표는 위에서 아래로 갈수록 y가 커지므로, 하트의 뾰족한 부분이
      아래로 향하도록 y 값을 뒤집어준다.
    """
    x, y = np.meshgrid(
        np.linspace(-1.5, 1.5, size),
        np.linspace(-1.5, 1.5, size),
    )
    y = -y

    heart_curve = (x**2 + y**2 - 1) ** 3 - (x**2) * (y**3)
    mask = np.where(heart_curve <= 0, 0, 255).astype(np.uint8)
    return mask


# ------------------------------------------------------------------
# 함수 5-2: 단어마다 무작위 '붉은 톤' 색을 골라주는 함수
# ------------------------------------------------------------------
def red_tone_color_func(word=None, font_size=None, position=None, orientation=None, random_state=None, **kwargs):
    """
    색상(hue)은 빨강(0)으로 고정하고, 채도/명도만 무작위로 바꿔서
    진한 빨강 ~ 밝은 빨강까지 다양한 '붉은 톤'을 만든다.
    """
    saturation = random.randint(65, 100)  # 채도: 선명함 정도
    lightness = random.randint(30, 55)  # 명도: 밝기 정도 (낮을수록 진한 빨강)
    return f"hsl(0, {saturation}%, {lightness}%)"


# ------------------------------------------------------------------
# 함수 5-3: 워드클라우드 이미지 만들기 (matplotlib 없이 이미지 객체만 반환)
# ------------------------------------------------------------------
def generate_wordcloud_image(word_counter: Counter, font_path: str):
    """
    단어별 등장 횟수(Counter)를 받아 하트 모양 + 붉은 톤 워드클라우드를 만든다.
    wordcloud 라이브러리의 to_image()는 PIL 이미지 객체를 돌려주므로,
    st.image()로 바로 화면에 띄울 수 있다 (matplotlib 불필요).
    """
    mask = make_heart_mask()

    wc = WordCloud(
        font_path=font_path,
        background_color="white",
        mask=mask,  # 하트 모양 안에만 글자를 채운다
        color_func=red_tone_color_func,  # 글자 색을 붉은 톤으로 통일
        contour_width=0,
        width=mask.shape[1],
        height=mask.shape[0],
        scale=2,  # 이미지를 2배 크기로 렌더링해서 해상도를 높인다
        min_font_size=4,
        random_state=42,
    )
    wc.generate_from_frequencies(word_counter)
    return wc.to_image()


# ------------------------------------------------------------------
# 메인 로직: 버튼을 누르면 댓글을 가져와서 화면에 보여준다
# ------------------------------------------------------------------
if st.button("댓글 가져오기", type="primary"):
    video_id = extract_video_id(url)

    if not video_id:
        # 링크 형식이 이상해서 영상 ID를 못 찾은 경우
        st.error(
            "영상 링크에서 영상 ID를 찾을 수 없어요. "
            "youtu.be/... 또는 youtube.com/watch?v=... 형태의 링크인지 확인해주세요."
        )
    else:
        # secrets.toml (또는 스트림릿 클라우드 Secrets)에서 API 키를 불러온다.
        api_key = st.secrets.get("YOUTUBE_API_KEY", None)

        if not api_key:
            st.error(
                "YouTube API 키가 설정되지 않았어요. "
                "스트림릿 클라우드의 Settings → Secrets에 YOUTUBE_API_KEY를 등록해주세요."
            )
            st.stop()

        with st.spinner("댓글을 가져오는 중이에요..."):
            comments = None
            try:
                comments = fetch_comments(video_id, api_key)
            except RuntimeError as e:
                # API가 명확한 에러를 준 경우 (댓글 막힘, 영상 없음 등)
                st.error(f"댓글을 가져오지 못했어요. {e}")
            except requests.exceptions.RequestException:
                # 네트워크 자체에 문제가 있는 경우
                st.error("네트워크 문제로 댓글을 가져오지 못했어요. 잠시 후 다시 시도해주세요.")

        if comments is not None:
            if len(comments) == 0:
                st.warning("이 영상에는 댓글이 없는 것 같아요.")
            else:
                # 좋아요 수가 많은 순으로 정렬
                comments.sort(key=lambda c: c["좋아요"], reverse=True)

                # 가져온 댓글 개수를 큰 지표 카드로 표시
                st.metric("가져온 댓글 개수", f"{len(comments)}개")

                # 댓글 목록을 표로 표시 (좋아요 많은 순)
                df = pd.DataFrame(comments)
                st.dataframe(df, use_container_width=True, hide_index=True)

                # 댓글 전체에서 단어별 등장 횟수를 한 번만 계산해서
                # TOP 20 막대그래프와 워드클라우드에 함께 사용한다.
                word_counter = get_word_counter(comments)

                # ------------------------------------------------------
                # 자주 나온 단어 TOP 20 (한 글자짜리 단어는 제외)
                # ------------------------------------------------------
                st.subheader("📊 자주 나온 단어 TOP 20")

                top_words = word_counter.most_common(20)

                if not top_words:
                    st.info("단어를 분석할 수 있는 댓글 내용이 부족해요.")
                else:
                    word_df = pd.DataFrame(top_words, columns=["단어", "횟수"])

                    # 가로 막대그래프는 데이터프레임의 첫 행이 아래쪽에 그려진다.
                    # 그래서 '많이 나온 단어가 위로' 오게 하려면 오름차순으로 정렬해야 한다.
                    word_df = word_df.sort_values("횟수", ascending=True)

                    fig = px.bar(
                        word_df,
                        x="횟수",
                        y="단어",
                        orientation="h",
                        text="횟수",
                        title="자주 나온 단어 TOP 20",
                    )
                    fig.update_layout(
                        xaxis_title="등장 횟수",
                        yaxis_title="단어",
                        height=600,
                    )
                    st.plotly_chart(fig, use_container_width=True)

                # ------------------------------------------------------
                # 워드클라우드 (한 글자짜리 단어는 제외, 흰색 배경)
                # ------------------------------------------------------
                st.subheader("❤️ 댓글 하트 워드클라우드")

                if not word_counter:
                    st.info("워드클라우드를 만들 수 있는 댓글 내용이 부족해요.")
                else:
                    font_path = download_font()

                    if not font_path:
                        # 폰트를 내려받지 못한 경우 (인터넷 문제 등)
                        st.error(
                            "한글 폰트를 내려받지 못해서 워드클라우드를 만들 수 없어요. "
                            "인터넷 연결을 확인한 뒤 새로고침해서 다시 시도해주세요."
                        )
                    else:
                        wc_image = generate_wordcloud_image(word_counter, font_path)
                        st.image(wc_image, use_container_width=True)
