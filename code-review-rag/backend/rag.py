import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from chunker import PythonChunker

class CodeRAG:
    def __init__(self, persist_dir="./chroma_db"):
        self.client = chromadb.PersistentClient(path=persist_dir)
        
       
        self.collection = self.client.get_or_create_collection(
            name="code_chunks",
            metadata={"hnsw:space": "cosine"}
        )
        
        self.embedder = SentenceTransformer('microsoft/codebert-base', device='cuda')
        self.chunker = PythonChunker()
    
    def add_code(self, code: str, filepath: str):
        chunks = self.chunker.chunk(code, filepath)
        if not chunks:
            # 如果没有解析出函数/类，将整个文件作为一个块
            chunks = [{
                'file': filepath,
                'name': 'whole_file',
                'type': 'file',
                'start_line': 1,
                'end_line': len(code.splitlines()),
                'code': code
            }]
        ids = []
        documents = []
        metadatas = []
        for i, chunk in enumerate(chunks):
            chunk_id = f"{filepath}_{chunk['start_line']}_{i}"
            ids.append(chunk_id)
            documents.append(chunk['code'])
            metadatas.append({
                'file': chunk['file'],
                'name': chunk['name'],
                'type': chunk['type'],
                'start_line': chunk['start_line'],
                'end_line': chunk['end_line']
            })
        embeddings = self.embedder.encode(documents).tolist()
        self.collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings
        )
       # self.client.persist()
    
    def search(self, query: str, top_k=5):
        query_embedding = self.embedder.encode([query]).tolist()
        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=top_k,
            include=['documents', 'metadatas']
        )
        return results['documents'][0] if results['documents'] else []
    
    def search_by_code(self, code_snippet: str, top_k=5):
        """根据代码片段检索最相关的项目块"""
        return self.search(code_snippet, top_k)
    
    def get_all_chunks(self, limit=1000):
        """获取所有已索引的块（用于批量审查）"""
        # Chroma 不支持直接获取全部，需要遍历，这里简单起见可返回所有文档
        # 实际项目中可存储一份块列表在内存
        pass

   

