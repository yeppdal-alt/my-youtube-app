import re  # 정규식으로 유튜브 링크 파싱 + 댓글에서 단어 뽑아내기에 사용
from collections import Counter  # 단어별 등장 횟수를 세기 위해 사용

import pandas as pd  # 댓글 목록을 표로 예쁘게 보여주기 위해 사용
import plotly.express as px  # 단어 빈도 막대그래프를 그리기 위해 사용
import requests  # YouTube Data API에 HTTP 요청을 보내기 위해 사용
import streamlit as st

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
# 함수 3: 댓글 전체에서 자주 나온 단어 상위 N개 세기
# ------------------------------------------------------------------
def count_top_words(comments: list, top_n: int = 20):
    """
    댓글들을 전부 이어붙인 뒤, 한글/영문/숫자 덩어리를 '단어'로 뽑아 개수를 센다.
    - 한 글자짜리 단어는 제외한다 (예: "이", "a" 등)
    - 영문은 대소문자를 구분하지 않도록 소문자로 통일한다
    - 등장 횟수가 많은 순으로 top_n개를 돌려준다 (word, count) 형태의 리스트
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

    counter = Counter(words)
    return counter.most_common(top_n)


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

                # ------------------------------------------------------
                # 자주 나온 단어 TOP 20 (한 글자짜리 단어는 제외)
                # ------------------------------------------------------
                st.subheader("📊 자주 나온 단어 TOP 20")

                top_words = count_top_words(comments, top_n=20)

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
