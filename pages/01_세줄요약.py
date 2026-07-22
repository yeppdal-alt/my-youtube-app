"""
유튜브 댓글 AI 요약 앱 - 1단계
----------------------------------
이 앱이 하는 일 (초보자용 설명):
1) 사용자가 유튜브 영상 링크를 입력하면
2) 그 링크에서 '영상 ID'만 뽑아내고
3) 유튜브 공식 API(YouTube Data API v3)에 요청을 보내서 댓글을 최대 100개 가져오고
4) 좋아요 많은 순으로 정렬해서 표로 보여준 다음
5) 'AI 세 줄 요약' 버튼을 누르면 업스테이지 Solar API를 이용해 댓글 전체 반응을 한국어 세 줄로 요약합니다.

스트림릿 클라우드에 올릴 때는 앱 설정의 Secrets 메뉴에 아래 두 값을 넣어주세요.
YOUTUBE_API_KEY = "여기에 유튜브 API 키"
SOLAR_API_KEY   = "여기에 업스테이지 Solar API 키"
"""

import streamlit as st
import pandas as pd
import requests
from urllib.parse import urlparse, parse_qs
from openai import OpenAI


# ----------------------------------------------------------------------------
# 0. 기본 설정값
# ----------------------------------------------------------------------------

# 입력창의 기본값 (예시 1과 동일한 링크)
DEFAULT_URL = "https://youtu.be/d95J8yzvjbQ?si=LfL5DLwCL8Pk077r"

# 예시 2 링크 (한국어 댓글이 많은 2002 월드컵 영상)
EXAMPLE_2_URL = "https://youtu.be/I9vK5EVTt0U?si=NEZ8L7MRuNvrzINa"

st.set_page_config(page_title="유튜브 댓글 AI 요약", page_icon="📺")

st.title("📺 유튜브 댓글 AI 요약 (1단계)")
st.caption("유튜브 영상 링크를 붙여넣으면 댓글을 가져오고, AI가 세 줄로 요약해줍니다.")


# ----------------------------------------------------------------------------
# 1. 세션 상태(session_state) 초기화
#    - 세션 상태는 스트림릿 앱이 새로고침(rerun)되어도 값이 유지되게 해주는 저장 공간입니다.
# ----------------------------------------------------------------------------

# 입력창에 표시될 링크 값 (버튼을 누르면 이 값이 바뀝니다)
if "url_input" not in st.session_state:
    st.session_state.url_input = DEFAULT_URL

# 가져온 댓글을 저장해 둘 자리 (아직 없으면 None)
if "comments_df" not in st.session_state:
    st.session_state.comments_df = None

# AI 요약 결과를 저장해 둘 자리
if "summary_text" not in st.session_state:
    st.session_state.summary_text = None


# 예시 버튼을 눌렀을 때 실행될 함수들
# -> 버튼의 on_click에 연결하면, 입력창이 다시 그려지기 '전에' 값을 바꿔줍니다.
def use_example_1():
    st.session_state.url_input = DEFAULT_URL


def use_example_2():
    st.session_state.url_input = EXAMPLE_2_URL


# ----------------------------------------------------------------------------
# 2. 예시 버튼 두 개 (나란히 배치)
# ----------------------------------------------------------------------------

col1, col2 = st.columns(2)
with col1:
    st.button(
        "예시 1 · 딥마인드 다큐(영어 댓글)",
        on_click=use_example_1,
        use_container_width=True,
    )
with col2:
    st.button(
        "예시 2 · 2002 월드컵 추억(한국어 댓글)",
        on_click=use_example_2,
        use_container_width=True,
    )


# ----------------------------------------------------------------------------
# 3. 유튜브 링크 입력창
#    - key="url_input" 을 넣으면 위 session_state.url_input 값과 자동으로 연결됩니다.
# ----------------------------------------------------------------------------

video_url = st.text_input("유튜브 영상 링크를 붙여넣으세요", key="url_input")


# ----------------------------------------------------------------------------
# 4. 링크에서 영상 ID 뽑아내는 함수
#    - youtu.be/영상ID?si=... (짧은 링크)
#    - youtube.com/watch?v=영상ID&... (긴 링크)
#    두 가지 형태를 모두 처리하고, si= 같은 나머지 파라미터는 무시합니다.
# ----------------------------------------------------------------------------

def extract_video_id(url: str):
    if not url:
        return None

    parsed = urlparse(url.strip())

    # 짧은 링크: https://youtu.be/영상ID?si=...
    if "youtu.be" in parsed.netloc:
        video_id = parsed.path.lstrip("/").split("/")[0]
        return video_id if video_id else None

    # 긴 링크: https://www.youtube.com/watch?v=영상ID&...
    if "youtube.com" in parsed.netloc:
        query_params = parse_qs(parsed.query)
        if "v" in query_params:
            return query_params["v"][0]
        # /shorts/영상ID, /embed/영상ID 형태도 혹시 몰라 함께 처리
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) >= 2 and path_parts[0] in ("shorts", "embed"):
            return path_parts[1]

    return None


# ----------------------------------------------------------------------------
# 5. 유튜브 댓글 가져오는 함수 (YouTube Data API v3 - commentThreads)
# ----------------------------------------------------------------------------

def fetch_comments(video_id: str, api_key: str):
    """
    유튜브 댓글을 최대 100개까지 가져와서
    [{"댓글": ..., "좋아요": ...}, ...] 형태의 리스트로 돌려줍니다.
    실패하면 예외(Exception)를 그대로 던집니다. (호출하는 쪽에서 try/except로 처리)
    """
    endpoint = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {
        "part": "snippet",       # 댓글 본문 정보만 요청
        "videoId": video_id,
        "order": "relevance",    # 최신순이 아니라 '좋아요 많은 순'에 가까운 관련도순
        "maxResults": 100,       # 최대 100개
        "key": api_key,
    }

    response = requests.get(endpoint, params=params, timeout=15)
    response.raise_for_status()  # 200이 아니면 여기서 에러 발생
    data = response.json()

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


# ----------------------------------------------------------------------------
# 6. AI 세 줄 요약 함수 (Solar API, openai 라이브러리 사용)
# ----------------------------------------------------------------------------

def summarize_comments(comments_df: pd.DataFrame, api_key: str) -> str:
    """
    댓글 전체를 Solar API(solar-open2 모델)에 보내서
    한국어 세 줄 요약 + 마지막 줄에 긍정/부정 비율 추정을 받아옵니다.
    """
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.upstage.ai/v1",  # Solar API 주소
    )

    # 댓글들을 한 덩어리의 텍스트로 합치기
    comments_text = "\n".join(f"- {text}" for text in comments_df["댓글"].tolist())

    prompt = (
        "다음은 어떤 유튜브 영상에 달린 댓글 목록입니다.\n"
        "이 댓글들을 읽고 시청자들의 전체 반응을 한국어로 정확히 세 줄로 요약해주세요.\n"
        "마지막(세 번째) 줄에는 댓글 반응이 대략 긍정 몇 %, 부정 몇 %인지 추정해서 함께 적어주세요.\n\n"
        f"댓글 목록:\n{comments_text}"
    )

    response = client.chat.completions.create(
        model="solar-open2",          # 모델 이름은 반드시 이 문자열 그대로
        messages=[{"role": "user", "content": prompt}],
        reasoning_effort="none",      # 추론(생각) 기능 끄기
    )

    return response.choices[0].message.content


# ----------------------------------------------------------------------------
# 7. '댓글 불러오기' 버튼 -> 실제 동작 실행
# ----------------------------------------------------------------------------

if st.button("💬 댓글 불러오기", type="primary"):

    video_id = extract_video_id(video_url)

    if not video_id:
        st.error(
            "😥 영상 ID를 찾지 못했어요. "
            "youtu.be/영상ID 또는 youtube.com/watch?v=영상ID 형태의 링크인지 확인해주세요."
        )
    else:
        # secrets에서 유튜브 API 키 불러오기
        youtube_api_key = st.secrets.get("YOUTUBE_API_KEY")

        if not youtube_api_key:
            st.error(
                "😥 유튜브 API 키가 설정되어 있지 않아요. "
                "앱 설정(Secrets)에 YOUTUBE_API_KEY 값을 추가해주세요."
            )
        else:
            with st.spinner("댓글을 가져오는 중이에요..."):
                try:
                    comments = fetch_comments(video_id, youtube_api_key)

                    if not comments:
                        st.warning("😥 이 영상에는 댓글이 없거나, 댓글 기능이 꺼져 있는 것 같아요.")
                        st.session_state.comments_df = None
                    else:
                        df = pd.DataFrame(comments)
                        # 좋아요 많은 순으로 정렬
                        df = df.sort_values(by="좋아요", ascending=False).reset_index(drop=True)
                        st.session_state.comments_df = df
                        st.session_state.summary_text = None  # 새로 불러왔으니 이전 요약은 초기화
                        st.success(f"댓글 {len(df)}개를 성공적으로 가져왔어요!")

                except requests.exceptions.RequestException:
                    st.error(
                        "😥 유튜브 댓글을 가져오는 데 실패했어요. "
                        "인터넷 연결, API 키, 또는 영상 ID가 올바른지 확인해주세요."
                    )
                    st.session_state.comments_df = None
                except Exception:
                    st.error(
                        "😥 알 수 없는 오류로 댓글을 가져오지 못했어요. "
                        "잠시 후 다시 시도해주세요."
                    )
                    st.session_state.comments_df = None


# ----------------------------------------------------------------------------
# 8. 댓글이 있으면 지표 카드 + 표 + 요약 버튼 보여주기
# ----------------------------------------------------------------------------

if st.session_state.comments_df is not None:
    df = st.session_state.comments_df

    st.divider()

    # 지표 카드: 가져온 댓글 개수
    st.metric("가져온 댓글 수", f"{len(df)}개")

    # 댓글 표 (좋아요 수와 함께)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()

    # AI 세 줄 요약 버튼
    if st.button("✨ AI 세 줄 요약"):
        solar_api_key = st.secrets.get("SOLAR_API_KEY")

        if not solar_api_key:
            st.error(
                "😥 Solar API 키가 설정되어 있지 않아요. "
                "앱 설정(Secrets)에 SOLAR_API_KEY 값을 추가해주세요."
            )
        else:
            with st.spinner("AI가 댓글을 읽고 요약하는 중이에요..."):
                try:
                    summary = summarize_comments(df, solar_api_key)
                    st.session_state.summary_text = summary
                except Exception:
                    st.error(
                        "😥 AI 요약에 실패했어요. "
                        "Solar API 키가 올바른지, 또는 잠시 후 다시 시도해주세요."
                    )
                    st.session_state.summary_text = None

    # 요약 결과 보여주기
    if st.session_state.summary_text:
        st.subheader("📋 AI 세 줄 요약")
        st.info(st.session_state.summary_text)
