"""
data/rag_documents 의 텍스트 파일로 ChromaDB 벡터 스토어를 생성합니다.

    python -m disaster_agent.rag.build
"""
import shutil

from langchain_chroma import Chroma
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from disaster_agent.config import CHROMA_DB_PATH, OPENAI_API_KEY, RAG_DOCUMENTS_PATH


def build_and_save_vector_store(rebuild: bool = False) -> None:
    """
    지정된 디렉토리의 텍스트 파일을 로드하여 ChromaDB 벡터 스토어를 생성하고 저장합니다.
    """
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인해주세요.")

    if rebuild and CHROMA_DB_PATH.exists():
        print(f"기존 벡터 DB를 삭제합니다: {CHROMA_DB_PATH}")
        shutil.rmtree(CHROMA_DB_PATH)

    print(f"1. '{RAG_DOCUMENTS_PATH}' 디렉토리에서 텍스트 파일을 로드합니다...")
    loader = DirectoryLoader(
        str(RAG_DOCUMENTS_PATH),
        glob="**/*.txt",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
        show_progress=True,
    )
    docs = loader.load()
    if not docs:
        print(f"경고: '{RAG_DOCUMENTS_PATH}' 디렉토리에서 문서를 찾을 수 없습니다.")
        return
    print(f"총 {len(docs)}개의 문서를 로드했습니다.\n")

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    print("2. 텍스트를 청크 단위로 분할합니다...")
    splits = text_splitter.split_documents(docs)
    print(f"총 {len(splits)}개의 청크로 분할되었습니다.\n")

    print(f"3. 임베딩 및 ChromaDB 저장을 시작합니다... (저장 경로: {CHROMA_DB_PATH})")
    Chroma.from_documents(
        documents=splits,
        embedding=OpenAIEmbeddings(api_key=OPENAI_API_KEY),
        persist_directory=str(CHROMA_DB_PATH),
    )
    print("ChromaDB에 성공적으로 저장했습니다.\n")


if __name__ == "__main__":
    # 직접 실행하면 기존 DB를 지우고 새로 생성합니다. (문서 추가/수정 후 사용)
    build_and_save_vector_store(rebuild=True)
