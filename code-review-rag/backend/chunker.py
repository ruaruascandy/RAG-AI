import tree_sitter_python as tspython
from tree_sitter import Language, Parser

class PythonChunker:
    def __init__(self):
        # 创建 Python 语言对象
        self.language = Language(tspython.language())
        self.parser = Parser(self.language)
    
    def chunk(self, code: str, filepath: str = "unknown") -> list:
        tree = self.parser.parse(bytes(code, 'utf8'))
        root = tree.root_node
        chunks = []
        
        def traverse(node):
            if node.type in ('function_definition', 'class_definition'):
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                chunk_code = code[node.start_byte:node.end_byte]
                # 获取函数/类名
                name_node = node.child_by_field_name('name')
                name = code[name_node.start_byte:name_node.end_byte] if name_node else 'unknown'
                chunks.append({
                    'file': filepath,
                    'name': name,
                    'type': node.type,
                    'start_line': start_line,
                    'end_line': end_line,
                    'code': chunk_code
                })
            for child in node.children:
                traverse(child)
        
        traverse(root)
        return chunks