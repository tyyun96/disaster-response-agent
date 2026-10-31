from functools import lru_cache

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from disaster_agent.config import CHROMA_DB_PATH, OPENAI_API_KEY


@lru_cache(maxsize=1)
def get_retriever():
    """
    저장된 ChromaDB를 로드하여 Retriever 객체를 반환합니다. (최초 호출 시 1회 생성)
    DB가 아직 없으면 data/rag_documents 로부터 자동으로 생성합니다.
    실패 시 None을 반환하며, 호출하는 쪽은 RAG 없이 동작해야 합니다.
    """
    if not OPENAI_API_KEY:
        print("OPENAI_API_KEY가 없어 RAG Retriever를 생성하지 않습니다.")
        return None

    try:
        if not (CHROMA_DB_PATH / "chroma.sqlite3").exists():
            from disaster_agent.rag.build import build_and_save_vector_store

            print(f"'{CHROMA_DB_PATH}'에 벡터 DB가 없어 새로 생성합니다...")
            build_and_save_vector_store()

        vectorstore = Chroma(
            persist_directory=str(CHROMA_DB_PATH),
            embedding_function=OpenAIEmbeddings(api_key=OPENAI_API_KEY),
        )
        print("RAG Retriever가 성공적으로 준비되었습니다.")
        return vectorstore.as_retriever(search_kwargs={"k": 10})
    except Exception as e:
        print(f"ChromaDB 로드 중 오류 발생: {e}")
        print("'python -m disaster_agent.rag.build'를 실행하여 DB를 다시 생성해보세요.")
        return None
