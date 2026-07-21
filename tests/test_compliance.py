from src.compliance import check_content, filter_for_report


class TestCheckContent:
    def test_passes_empty_text(self):
        passed, v = check_content("")
        assert passed
        assert v == []

    def test_passes_attributed_recommendation(self):
        """'高盛建议买入' is attributed → should pass."""
        passed, v = check_content("高盛维持英伟达买入评级，目标价200美元")
        assert passed
        assert v == []

    def test_passes_attributed_target_price(self):
        passed, v = check_content("高盛目标价上调至250美元")
        assert passed

    def test_blocks_unattributed_advice(self):
        passed, v = check_content("我们建议买入这只股票")
        assert not passed
        assert len(v) >= 1

    def test_blocks_unattributed_sell(self):
        passed, v = check_content("建议卖出")
        assert not passed
        assert "建议卖出" in v

    def test_blocks_recommend_keyword(self):
        passed, v = check_content("推荐买入英伟达")
        assert not passed
        assert "推荐买入" in v

    def test_gaosheng_attribution_overrides_banned_pattern(self):
        """'高盛建议买入' has both attribution AND banned pattern → passes."""
        passed, v = check_content("高盛建议买入苹果，目标价看至300美元")
        assert passed


class TestFilterForReport:
    def test_sanitizes_banned_content(self):
        text = "我们建议买入这只股票，长期看好。"
        sanitized, v = filter_for_report(text)
        assert "我们建议" not in sanitized
        assert "合规脱敏" in sanitized
        assert len(v) >= 1

    def test_preserves_clean_content(self):
        text = "高盛维持英伟达买入评级，目标价200美元。"
        sanitized, v = filter_for_report(text)
        assert sanitized == text
        assert v == []
