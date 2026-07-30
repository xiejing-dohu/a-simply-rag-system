from typing import AsyncGenerator
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from app.services.model_service import get_llm_instance
from app.rag.retriever import search_similar

def build_rag_chain(model_name: str, collection_name: str = None):
    llm = get_llm_instance(model_name)
    
    if collection_name:
        system_prompt = """你是一个智能助手，请根据提供的参考上下文来回答用户的问题。
如果你不知道答案，请直接说不知道，不要编造答案。

参考上下文：
{context}"""
    else:
        system_prompt = "你是一个智能助手，请尽力回答用户的问题。"
        
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{question}")
    ])
    
    if collection_name:
        def format_docs(question: str):
            docs = search_similar(collection_name, question)
            return "\n\n".join(docs)
            
        chain = (
            {"context": lambda x: format_docs(x["question"]), "question": lambda x: x["question"], "history": lambda x: x["history"]}
            | prompt
            | llm
            | StrOutputParser()
        )
    else:
        chain = (
            prompt
            | llm
            | StrOutputParser()
        )
        
    return chain

async def stream_chat(chain, question: str, history: list) -> AsyncGenerator[str, None]:
    formatted_history = []
    for role, content in history:
        if role == "user":
            formatted_history.append(("human", content))
        elif role == "assistant":
            formatted_history.append(("ai", content))
            
    async for chunk in chain.astream({"question": question, "history": formatted_history}):
        yield chunk
