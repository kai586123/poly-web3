# -*- coding = utf-8 -*-
# @Time: 2025-12-27 16:01:00
# @Author: PinBar
# @Site:
# @File: safe_service.py
# @Software: PyCharm
from py_builder_relayer_client.models import OperationType, SafeTransaction
from poly_web3.web3_service.base import BaseWeb3Service


class SafeWeb3Service(BaseWeb3Service):
    def _build_redeem_tx(self, to: str, data: str) -> SafeTransaction:
        return SafeTransaction(
            to=to,
            data=data,
            value="0",
            operation=OperationType.Call,
        )

    def _submit_transactions(
            self, txs: list[SafeTransaction], metadata: str
    ) -> dict | None:
        if self.relayer_client is None:
            raise Exception("relayer_client not found")
        try:
            resp = self.relayer_client.execute(txs, metadata)
            result = resp.wait()
        except Exception as exc:
            self._raise_relayer_quota_exceeded_if_needed(exc)
            raise
        self._raise_relayer_quota_exceeded_if_needed(result)
        return result

    def _submit_redeem(self, txs: list[SafeTransaction]) -> dict | None:
        return self._submit_transactions(txs, "redeem")
