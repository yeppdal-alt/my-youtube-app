import re  # 댓글에서 단어를 뽑아내기 위해 사용
import tempfile  # 폰트 파일을 저장할 임시 폴더 경로를 얻기 위해 사용
from collections import Counter  # 단어별 등장 횟수를 세기 위해 사용

import requests  # 폰트 파일을 다운로드하기 위해 사용
import streamlit as st
from wordcloud import WordCloud  # 워드클라우드 이미지를 만들기 위해 사용

st.set_page_config(page_title="워드클라우드", page_icon="☁️", layout="centered")

st.title("☁️ 댓글 워드클라우드")
st.caption("3단계: 메인 페이지에서 불러온 댓글로 워드클라우드를 그려요.")

# 한글이 깨지지 않도록 사용할 나눔고딕 폰트 파일 주소
FONT_URL = (
    "https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/"
    "NanumGothic-Regular.ttf"
)
FONT_PATH = f"{tempfile.gettempdir()}/NanumGothic-Regular.ttf"


# ------------------------------------------------------------------
# 함수 1: 한글 폰트 파일 다운로드 (같은 세션에서는 한 번만 받도록 캐시)
# ------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def download_font():
    """
    나눔고딕 폰트를 다운로드해서 임시 폴더에 저장하고 경로를 돌려준다.
    다운로드에 실패하면 예외가 발생한다 (호출하는 쪽에서 처리).
    """
    response = requests.get(FONT_URL, timeout=15)
    response.raise_for_status()  # 200이 아니면 에러를 발생시킨다

    with open(FONT_PATH, "wb") as f:
        f.write(response.content)

    return FONT_PATH


# ------------------------------------------------------------------
# 함수 2: 댓글에서 단어별 등장 횟수 세기 (2단계와 동일한 방식)
# ------------------------------------------------------------------
def build_word_frequencies(comments: list):
    """
    댓글을 전부 이어붙인 뒤 한글/영문/숫자 덩어리를 단어로 뽑는다.
    한 글자짜리 단어는 제외하고, {단어: 등장횟수} 형태로 돌려준다.
    """
    all_text = " ".join(c["댓글"] for c in comments)
    raw_words = re.findall(r"[A-Za-z0-9]+|[가-힣]+", all_text)

    words = []
    for w in raw_words:
        w = w.lower()  # 영문 대소문자 통일
        if len(w) >= 2:  # 한 글자짜리 단어는 제외
            words.append(w)

    return Counter(words)


# ------------------------------------------------------------------
# 메인 로직
# ------------------------------------------------------------------
# 메인 페이지에서 댓글을 불러왔다면 st.session_state["comments"]에 저장되어 있다.
comments = st.session_state.get("comments")

if not comments:
    st.info("먼저 메인 페이지에서 유튜브 영상 링크를 넣고 댓글을 불러와주세요.")
else:
    st.metric("워드클라우드에 사용한 댓글 개수", f"{len(comments)}개")

    # 1) 한글 폰트 준비 (실패하면 친절한 한국어 안내만 보여주고 멈춘다)
    font_path = None
    try:
        with st.spinner("한글 폰트를 준비하는 중이에요..."):
            font_path = download_font()
    except requests.exceptions.RequestException:
        st.error(
            "한글 폰트 파일을 내려받지 못했어요. "
            "인터넷 연결 상태를 확인한 뒤 페이지를 새로고침해주세요."
        )

    # 2) 폰트 준비에 성공했을 때만 워드클라우드를 그린다
    if font_path:
        word_freq = build_word_frequencies(comments)

        if not word_freq:
            st.warning("워드클라우드를 그릴 만한 단어가 부족해요.")
        else:
            wordcloud = WordCloud(
                font_path=font_path,       # 한글 깨짐 방지용 폰트
                background_color="white",  # 배경 흰색
                width=800,
                height=500,
            ).generate_from_frequencies(word_freq)

            # matplotlib 없이, wordcloud가 만들어주는 PIL 이미지를 바로 화면에 띄운다.
            image = wordcloud.to_image()
            st.image(image, use_container_width=True)
