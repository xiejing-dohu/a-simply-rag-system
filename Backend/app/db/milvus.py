from pymilvus import connections, utility, Collection, CollectionSchema, FieldSchema, DataType
from app.core.config import settings

def get_milvus_connection():
    """获取 Milvus 连接"""
    connections.connect("default", host=settings.MILVUS_HOST, port=str(settings.MILVUS_PORT))

def create_knowledge_collection(collection_name: str):
    """创建向量集合 (1536维)"""
    get_milvus_connection()
    if utility.has_collection(collection_name):
        return Collection(collection_name)
    
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1536)
    ]
    schema = CollectionSchema(fields, description=f"知识库集合: {collection_name}")
    collection = Collection(name=collection_name, schema=schema)
    
    index_params = {
        "metric_type": "L2",
        "index_type": "IVF_FLAT",
        "params": {"nlist": 1024}
    }
    collection.create_index(field_name="embedding", index_params=index_params)
    return collection

def delete_collection(collection_name: str):
    """删除集合"""
    get_milvus_connection()
    if utility.has_collection(collection_name):
        utility.drop_collection(collection_name)
