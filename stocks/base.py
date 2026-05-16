from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import pandas as pd


@dataclass
class Signal:
    action: str
    action_price: float
    details: dict = field(default_factory=dict)


class BaseStrategy(ABC):
    def __init__(
        self,
        stock_code: str,
        stock_name: str,
        init_cash: float = 100000,
        commission: float = 0.001,
    ):
        self.stock_code = stock_code
        self.stock_name = stock_name
        self.init_cash = init_cash
        self.commission = commission

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, params: dict = None) -> Signal:
        ...

    @abstractmethod
    def backtest(
        self, df: pd.DataFrame, params: dict
    ) -> tuple[float, list[dict], int]:
        ...

    @abstractmethod
    def param_grid(self, df: pd.DataFrame) -> list[dict]:
        ...

    @abstractmethod
    def describe_params(self, params: dict) -> str:
        ...
