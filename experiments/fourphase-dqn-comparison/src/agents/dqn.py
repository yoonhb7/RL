"""Configuration and inference adapter for Stable-Baselines3's vanilla DQN."""

import hashlib
import json
import math
from pathlib import Path

from src.traffic.experiments import ROOT, validate_splits


def read_dqn_config(path=None, *, timesteps=None, device=None):
    path = Path(path) if path else ROOT / "configs" / "toy_dqn.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    if timesteps is not None:
        config["total_timesteps"] = timesteps
    if device is not None:
        config["device"] = device
    validate_splits(config)
    for key in ("total_timesteps", "buffer_size", "learning_starts", "batch_size", "train_freq", "gradient_steps",
                "target_update_interval", "validation_frequency"):
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{key} must be a positive integer")
    if config["total_timesteps"] <= config["learning_starts"]:
        raise ValueError("학습 스텝 수는 learning_starts보다 커야 합니다")
    if config["buffer_size"] < max(config["batch_size"], config["learning_starts"]):
        raise ValueError("Replay buffer is too small")
    for key in ("learning_rate", "gamma", "exploration_fraction", "exploration_initial_eps", "exploration_final_eps"):
        if not math.isfinite(config[key]) or config[key] < 0:
            raise ValueError(f"Invalid {key}")
    if config["learning_rate"] <= 0 or not 0 < config["gamma"] <= 1 or not 0 < config["exploration_fraction"] <= 1:
        raise ValueError("Invalid learning rate, discount, or exploration fraction")
    if not 0 <= config["exploration_final_eps"] <= config["exploration_initial_eps"] <= 1:
        raise ValueError("Exploration probabilities must satisfy 0 <= final <= initial <= 1")
    if not config["net_arch"] or any(isinstance(n, bool) or not isinstance(n, int) or n <= 0 for n in config["net_arch"]):
        raise ValueError("net_arch must contain positive layer sizes")
    return config


def create_dqn(env, config):
    from stable_baselines3 import DQN

    keys = ("learning_rate", "buffer_size", "learning_starts", "batch_size", "gamma", "train_freq", "gradient_steps",
            "target_update_interval", "exploration_fraction", "exploration_initial_eps", "exploration_final_eps", "seed", "device")
    return DQN("MlpPolicy", env, **{key: config[key] for key in keys},
               policy_kwargs={"net_arch": config["net_arch"]}, n_steps=1, verbose=1)


class DQNController:
    def __init__(self, model):
        self.model = model

    def choose_action(self, observation, info):
        action, _ = self.model.predict(observation, deterministic=True)
        return int(action)


def load_dqn_controller(path):
    from stable_baselines3 import DQN

    path = Path(path).resolve()
    model = DQN.load(str(path), device="cpu")
    if model.observation_space.shape != (16,) or getattr(model.action_space, "n", None) != 2:
        raise ValueError("이 모델은 16차원 관측과 2개 행동의 ToyTrafficEnv 모델이 아닙니다")
    version = "dqn:" + hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return DQNController(model), version


def model_env_settings(path):
    manifest = Path(path).resolve().parent / "manifest.json"
    if not manifest.is_file():
        raise FileNotFoundError("모델 옆에 학습 조건을 기록한 manifest.json이 필요합니다")
    return json.loads(manifest.read_text(encoding="utf-8"))["env_settings"]
