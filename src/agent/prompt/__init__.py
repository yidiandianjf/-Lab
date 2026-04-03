"""
Prompt模块 - 存放DM Agent和状态推演系统的Prompt模板

使用方法:
    from src.agent.prompt import SYSTEM_PROMPT, STATE_EVOLUTION_PROMPT
    
    # 加载系统提示词
    with open(SYSTEM_PROMPT, 'r', encoding='utf-8') as f:
        prompt = f.read()
    
    # 或直接使用加载函数
    from src.agent.prompt import load_system_prompt, load_state_evolution_prompt
    prompt = load_state_evolution_prompt()
"""

import os

# Prompt文件路径
SYSTEM_PROMPT = os.path.join(os.path.dirname(__file__), 'system_prompt.md')
STATE_EVOLUTION_PROMPT = os.path.join(os.path.dirname(__file__), 'state_evolution_prompt.md')


def load_system_prompt() -> str:
    """
    加载DM Agent系统提示词
    
    Returns:
        系统提示词内容
    
    Raises:
        FileNotFoundError: 提示词文件不存在
    """
    with open(SYSTEM_PROMPT, 'r', encoding='utf-8') as f:
        return f.read()


def load_state_evolution_prompt() -> str:
    """
    加载状态推演系统提示词
    
    Returns:
        状态推演系统提示词内容
    
    Raises:
        FileNotFoundError: 提示词文件不存在
    """
    with open(STATE_EVOLUTION_PROMPT, 'r', encoding='utf-8') as f:
        return f.read()


__all__ = [
    'SYSTEM_PROMPT',
    'STATE_EVOLUTION_PROMPT',
    'load_system_prompt',
    'load_state_evolution_prompt'
]
