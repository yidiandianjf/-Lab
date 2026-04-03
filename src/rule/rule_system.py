"""
COC规则系统 - 负责鉴定计算逻辑
纯计算模块，不涉及LLM调用
"""

import random
from typing import List, Optional, Dict, Any
from src.data.models import (
    CheckInput,
    CheckOutput,
    CheckType,
    CheckDifficulty,
    CheckResult,
    Character,
)


def roll_d100() -> int:
    """
    投掷d100骰子
    
    Returns:
        int: 1-100的随机整数
    """
    return random.randint(1, 100)


def calculate_target_value(base_value: int, difficulty: CheckDifficulty) -> int:
    """
    根据难度计算目标值
    
    Args:
        base_value: 基础属性值
        difficulty: 难度等级
        
    Returns:
        int: 调整后的目标值
    """
    if difficulty == CheckDifficulty.REGULAR:
        return base_value
    elif difficulty == CheckDifficulty.HARD:
        return base_value // 2
    elif difficulty == CheckDifficulty.EXTREME:
        return base_value // 5
    else:
        return base_value


def determine_result(dice_roll: int, target_value: int) -> CheckResult:
    """
    根据骰子结果和目标值判定成功等级
    
    COC判定规则:
    - 大成功: 骰子 == 1 或 骰子 <= 目标值/5 (取较小)
    - 成功: 骰子 <= 目标值
    - 失败: 骰子 > 目标值
    - 大失败: 骰子 == 100 或 骰子 >= 96+ (当目标值<50时)
    
    Args:
        dice_roll: 骰子结果 (1-100)
        target_value: 目标值
        
    Returns:
        CheckResult: 鉴定结果等级
    """
    # 大成功判定
    # COC常用写法：至少保留1点大成功阈值，技能高时扩展到1/5
    critical_threshold = max(1, target_value // 5)
    if dice_roll == 1 or dice_roll <= critical_threshold:
        return CheckResult.CRITICAL_SUCCESS
    
    # 普通成功判定
    if dice_roll <= target_value:
        return CheckResult.SUCCESS
    
    # 大失败判定
    fumble_threshold = 100 if target_value < 50 else 100
    if dice_roll == 100:
        return CheckResult.FUMBLE
    if target_value < 50 and dice_roll >= 96:
        return CheckResult.FUMBLE
    
    # 普通失败
    return CheckResult.FAILURE


def get_attribute_value(character: Character, attribute_name: str) -> Optional[int]:
    """
    从角色对象中获取属性值（COC规则：属性值 × 5 = 鉴定成功率）
    
    支持的属性名:
    - 主属性: str, con, siz, dex, app, int, pow, edu（自动×5转换为成功率）
    - 状态值: hp, san, lucky（直接使用原始值）
    - 别名: luck (映射到lucky)
    
    Args:
        character: 角色对象
        attribute_name: 属性名称
        
    Returns:
        Optional[int]: 属性值，如果属性不存在则返回None
    """
    attr_lower = attribute_name.lower()
    
    # 主属性映射（COC标准：属性值 × 5% = 鉴定成功率）
    main_attributes = {
        'str': 'str',
        'con': 'con',
        'siz': 'siz',
        'dex': 'dex',
        'app': 'app',
        'int': 'int',
        'pow': 'pow',
        'edu': 'edu',
    }
    
    # 检查主属性
    if attr_lower in main_attributes:
        base_value = getattr(character.attributes, main_attributes[attr_lower], None)
        return base_value * 5 if base_value is not None else None
    
    # 检查状态值
    status_mapping = {
        'hp': 'hp',
        'san': 'san',
        'lucky': 'lucky',
        'luck': 'lucky',  # 别名
    }
    
    if attr_lower in status_mapping:
        return getattr(character.status, status_mapping[attr_lower], None)
    
    return None


def get_combined_attribute_value(
    character: Character,
    attributes: List[str]
) -> Optional[int]:
    """
    获取多个属性的组合值（取平均值，向下取整）
    
    Args:
        character: 角色对象
        attributes: 属性名称列表
        
    Returns:
        Optional[int]: 平均属性值，如果有任一属性不存在则返回None
    """
    if not attributes:
        return None
    
    values = []
    for attr in attributes:
        value = get_attribute_value(character, attr)
        if value is None:
            return None
        values.append(value)
    
    return sum(values) // len(values)


def perform_regular_check(
    check_input: CheckInput,
    actor: Character,
) -> CheckOutput:
    """
    执行非对抗鉴定
    
    Args:
        check_input: 鉴定输入参数
        actor: 行动者角色
        
    Returns:
        CheckOutput: 鉴定结果
    """
    # 获取行动者属性值（多个属性取平均）
    actor_value = get_combined_attribute_value(actor, check_input.attributes)
    if actor_value is None:
        raise ValueError(f"无法获取角色 {actor.id} 的属性值: {check_input.attributes}")
    
    # 计算目标值（考虑难度）
    target_value = calculate_target_value(actor_value, check_input.difficulty)
    
    # 投掷骰子
    dice_roll = roll_d100()
    
    # 判定结果
    result = determine_result(dice_roll, target_value)
    
    # 生成详细说明
    detail = generate_result_detail(
        result=result,
        dice_roll=dice_roll,
        target_value=target_value,
        actor_value=actor_value,
        difficulty=check_input.difficulty,
        attributes=check_input.attributes,
    )
    
    return CheckOutput(
        result=result,
        dice_roll=dice_roll,
        target_value=target_value,
        actor_value=actor_value,
        detail=detail,
    )


def perform_opposed_check(
    check_input: CheckInput,
    actor: Character,
    target: Character,
) -> CheckOutput:
    """
    执行对抗鉴定
    
    对抗鉴定规则:
    - 双方各自进行鉴定
    - 成功等级高者获胜
    - 成功等级相同时，目标值高者获胜
    - 都失败时，目标值高者获胜
    
    Args:
        check_input: 鉴定输入参数
        actor: 行动者角色
        target: 目标角色
        
    Returns:
        CheckOutput: 鉴定结果（从行动者视角）
    """
    # 获取双方属性值
    actor_value = get_combined_attribute_value(actor, check_input.attributes)
    if actor_value is None:
        raise ValueError(f"无法获取角色 {actor.id} 的属性值: {check_input.attributes}")
    
    # 目标通常使用相同属性进行对抗
    target_value = get_combined_attribute_value(target, check_input.attributes)
    if target_value is None:
        raise ValueError(f"无法获取角色 {target.id} 的属性值: {check_input.attributes}")
    
    # 行动者投掷
    actor_dice = roll_d100()
    actor_target = calculate_target_value(actor_value, check_input.difficulty)
    actor_result = determine_result(actor_dice, actor_target)
    
    # 目标投掷（常规难度）
    target_dice = roll_d100()
    target_result = determine_result(target_dice, target_value)
    
    # 判定胜负
    final_result = resolve_opposed_result(
        actor_result=actor_result,
        target_result=target_result,
        actor_target=actor_target,
        target_target=target_value,
    )
    
    # 生成详细说明
    detail = generate_opposed_detail(
        actor_result=actor_result,
        target_result=target_result,
        actor_dice=actor_dice,
        target_dice=target_dice,
        actor_target=actor_target,
        target_target=target_value,
        actor_value=actor_value,
        target_value=target_value,
        final_result=final_result,
        attributes=check_input.attributes,
    )
    
    return CheckOutput(
        result=final_result,
        dice_roll=actor_dice,
        target_value=actor_target,
        actor_value=actor_value,
        detail=detail,
    )


def resolve_opposed_result(
    actor_result: CheckResult,
    target_result: CheckResult,
    actor_target: int,
    target_target: int,
) -> CheckResult:
    """
    解析对抗鉴定的最终结果
    
    优先级:
    1. 大成功 > 成功 > 失败 > 大失败
    2. 成功等级相同: 目标值高者胜
    3. 都失败: 目标值高者胜
    
    Args:
        actor_result: 行动者结果
        target_result: 目标结果
        actor_target: 行动者目标值
        target_target: 目标目标值
        
    Returns:
        CheckResult: 从行动者视角的最终结果
    """
    # 结果等级权重
    result_priority = {
        CheckResult.CRITICAL_SUCCESS: 4,
        CheckResult.SUCCESS: 3,
        CheckResult.FAILURE: 2,
        CheckResult.FUMBLE: 1,
    }
    
    actor_priority = result_priority[actor_result]
    target_priority = result_priority[target_result]
    
    # 成功等级不同，高者胜
    if actor_priority > target_priority:
        return CheckResult.SUCCESS if actor_result == CheckResult.CRITICAL_SUCCESS else actor_result
    elif target_priority > actor_priority:
        # 从行动者视角，目标胜意味着行动者失败
        return CheckResult.FAILURE
    
    # 成功等级相同，比较目标值
    if actor_target >= target_target:
        return CheckResult.SUCCESS if actor_result == CheckResult.CRITICAL_SUCCESS else actor_result
    else:
        return CheckResult.FAILURE


def generate_result_detail(
    result: CheckResult,
    dice_roll: int,
    target_value: int,
    actor_value: int,
    difficulty: CheckDifficulty,
    attributes: List[str],
) -> str:
    """
    生成非对抗鉴定的详细说明
    
    Args:
        result: 鉴定结果
        dice_roll: 骰子结果
        target_value: 目标值
        actor_value: 行动者属性值
        difficulty: 难度等级
        attributes: 使用的属性列表
        
    Returns:
        str: 详细说明文本
    """
    attr_str = "+".join(attributes)
    diff_str = f"[{difficulty.value}]" if difficulty != CheckDifficulty.REGULAR else ""
    
    base_detail = f"使用属性: {attr_str}={actor_value}"
    if difficulty != CheckDifficulty.REGULAR:
        base_detail += f", {difficulty.value}难度目标值={target_value}"
    
    result_detail = f", 骰子={dice_roll}"
    
    return base_detail + result_detail


def generate_opposed_detail(
    actor_result: CheckResult,
    target_result: CheckResult,
    actor_dice: int,
    target_dice: int,
    actor_target: int,
    target_target: int,
    actor_value: int,
    target_value: int,
    final_result: CheckResult,
    attributes: List[str],
) -> str:
    """
    生成对抗鉴定的详细说明
    
    Args:
        actor_result: 行动者原始结果
        target_result: 目标原始结果
        actor_dice: 行动者骰子
        target_dice: 目标骰子
        actor_target: 行动者目标值
        target_target: 目标目标值
        actor_value: 行动者属性值
        target_value: 目标属性值
        final_result: 最终结果
        attributes: 使用的属性列表
        
    Returns:
        str: 详细说明文本
    """
    attr_str = "+".join(attributes)
    
    actor_info = f"行动者: {attr_str}={actor_value}, 骰子={actor_dice}, 结果={actor_result.value}"
    target_info = f"目标: {attr_str}={target_value}, 骰子={target_dice}, 结果={target_result.value}"
    
    return f"{actor_info}; {target_info}"


def perform_check(
    check_input: CheckInput,
    actor: Character,
    target: Optional[Character] = None,
) -> CheckOutput:
    """
    执行鉴定的主入口函数
    
    Args:
        check_input: 鉴定输入参数
        actor: 行动者角色
        target: 目标角色（对抗鉴定时需要）
        
    Returns:
        CheckOutput: 鉴定结果
        
    Raises:
        ValueError: 当属性值无法获取或对抗鉴定缺少目标时
    """
    if check_input.check_type == CheckType.REGULAR:
        return perform_regular_check(check_input, actor)
    elif check_input.check_type == CheckType.OPPOSED:
        if target is None:
            raise ValueError("对抗鉴定需要提供目标角色")
        return perform_opposed_check(check_input, actor, target)
    else:
        raise ValueError(f"未知的鉴定类型: {check_input.check_type}")


class RuleSystem:
    """规则系统门面类，供引擎统一调用。"""

    def execute_check(self, check_input: CheckInput, game_state) -> CheckOutput:
        actor = game_state.characters.get(check_input.actor_id)
        if not actor:
            raise ValueError(f"行动者不存在: {check_input.actor_id}")

        target = None
        if check_input.check_type == CheckType.OPPOSED:
            if not check_input.target_id:
                raise ValueError("对抗鉴定缺少target_id")
            target = game_state.characters.get(check_input.target_id)
            if not target:
                raise ValueError(f"对抗目标不存在: {check_input.target_id}")

        return perform_check(check_input, actor, target)
