"""
一致性检查器测试

测试 ConsistencyChecker 的核心功能
"""

import pytest
from unittest.mock import MagicMock, patch


class TestConsistencyChecker:
    """ConsistencyChecker 测试类"""

    def test_consistency_checker_init(self):
        """测试初始化"""
        # 延迟导入避免 pydantic 依赖问题
        pytest.importorskip("pydantic")
        from src.utils.debug_consistency import ConsistencyChecker

        io_system = MagicMock()
        logger = MagicMock()

        checker = ConsistencyChecker(io_system, logger)

        assert checker.io_system == io_system
        assert checker.logger == logger

    def test_check_after_change_item_location(self):
        """测试物品 location 变更后的检查"""
        pytest.importorskip("pydantic")
        from src.utils.debug_consistency import ConsistencyChecker

        io_system = MagicMock()
        logger = MagicMock()
        checker = ConsistencyChecker(io_system, logger)

        # 模拟 IO 层返回的物品
        io_item = MagicMock()
        io_item.location = "char-player-01"
        io_system.get_item.return_value = io_item

        # 模拟内存状态
        memory_state = MagicMock()
        memory_item = MagicMock()
        memory_item.location = "char-player-01"
        memory_state.items = {"item-book-01": memory_item}
        memory_state.characters = {}

        # 模拟 IO 层角色
        io_char = MagicMock()
        io_char.inventory = ["item-book-01"]
        io_system.get_character.return_value = io_char

        # 执行检查
        inconsistencies = checker.check_after_change("item-book-01", "location", memory_state)

        # 验证：如果没有不一致，返回空列表
        assert isinstance(inconsistencies, list)

    def test_verify_inventory_sync(self):
        """测试 inventory 同步验证"""
        pytest.importorskip("pydantic")
        from src.utils.debug_consistency import ConsistencyChecker

        io_system = MagicMock()
        checker = ConsistencyChecker(io_system)

        # 模拟内存角色
        memory_char = MagicMock()
        memory_char.inventory = ["item-book-01"]

        # 模拟内存物品
        memory_item = MagicMock()
        memory_item.location = "char-player-01"

        memory_state = MagicMock()
        memory_state.characters = {"char-player-01": memory_char}
        memory_state.items = {"item-book-01": memory_item}

        # 模拟 IO 层
        io_char = MagicMock()
        io_char.inventory = ["item-book-01"]
        io_item = MagicMock()
        io_item.location = "char-player-01"

        io_system.get_character.return_value = io_char
        io_system.get_item.return_value = io_item

        # 执行检查
        result = checker.verify_inventory_sync("char-player-01", memory_state)

        # 验证：如果没有不一致，返回 None
        assert result is None

    def test_check_entity_consistency_not_found(self):
        """测试实体不存在的情况"""
        pytest.importorskip("pydantic")
        from src.utils.debug_consistency import ConsistencyChecker

        io_system = MagicMock()
        io_system.get_character.return_value = None

        checker = ConsistencyChecker(io_system)

        memory_state = MagicMock()
        memory_char = MagicMock()
        memory_state.characters = {"char-player-01": memory_char}
        memory_state.items = {}
        memory_state.maps = {}

        result = checker.check_entity_consistency("char-player-01", memory_state)

        # 验证：实体不存在时返回不一致记录
        assert result is not None
        assert result.entity_id == "char-player-01"
        assert result.field == "existence"


class TestDebugLoggerIntegration:
    """DebugLogger 集成测试"""

    def test_enable_consistency_checking(self):
        """测试启用一致性检查"""
        from src.utils.debug_logger import DebugLogger

        logger = DebugLogger()
        io_system = MagicMock()

        # 启用一致性检查
        logger.enable_consistency_checking(io_system)

        # 验证一致性检查器已设置
        assert logger._consistency_checker is not None

    def test_log_state_change_applied_with_consistency_check(self):
        """测试状态变更应用时的一致性检查"""
        pytest.importorskip("pydantic")
        from src.utils.debug_logger import DebugLogger

        logger = DebugLogger()
        io_system = MagicMock()

        # 启用一致性检查
        logger.enable_consistency_checking(io_system)

        # 模拟一致性检查器
        mock_checker = MagicMock()
        logger._consistency_checker = mock_checker

        # 模拟状态变更
        change = MagicMock()
        change.id = "item-book-01"
        change.field = "location"
        change.value = "char-player-01"

        # 模拟游戏状态
        game_state = MagicMock()

        # 记录状态变更（触发一致性检查）
        logger.log_state_change_applied(change, error_code=0, game_state=game_state)

        # 验证一致性检查被调用
        mock_checker.check_after_change.assert_called_once_with("item-book-01", "location", game_state)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
