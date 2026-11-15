"""Training logs and checkpoint selection using validation demand only."""

import csv
import statistics

from stable_baselines3.common.callbacks import BaseCallback

from src.agents.evaluation import run_episode


class ToyTrainingCallback(BaseCallback):
    def __init__(self, folder, manifest, *, episode_runner=run_episode):
        super().__init__()
        self.folder = folder
        self.manifest = manifest
        self.episode_runner = episode_runner
        self.best_score = -float("inf")
        self.episode_count = 0
        self.handles = []
        self.writers = {}
        fields = {
            "episodes": ["global_step", "episode", "episode_return", "episode_length", "arrived", "unfinished", "pending"],
            "progress": ["global_step", "optimizer_updates", "exploration_rate", "replay_size"],
            "validation": ["global_step", "optimizer_updates", "mean_return", "std_return", "selected", "unfinished", "pending"],
        }
        for name, columns in fields.items():
            handle = (folder / f"{name}.csv").open("w", newline="", encoding="utf-8")
            self.handles.append(handle)
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            self.writers[name] = writer

    def flush(self):
        for handle in self.handles:
            handle.flush()

    def close(self):
        for handle in self.handles:
            handle.close()

    def validate(self):
        results = [self.episode_runner(self.folder, case, self.manifest["env_settings"], model=self.model)
                   for case in self.manifest["cases"]["validation"]]
        returns = [result["episode_return"] for result in results]
        mean = statistics.fmean(returns)
        selected = mean > self.best_score
        if selected:
            self.best_score = mean
            self.model.save(str(self.folder / "best_model.zip"))
        self.writers["validation"].writerow({
            "global_step": self.model.num_timesteps, "optimizer_updates": self.model._n_updates,
            "mean_return": mean, "std_return": statistics.stdev(returns) if len(returns) > 1 else 0.0,
            "selected": selected,
            "unfinished": sum(result["final_info"]["vehicles_running"] for result in results),
            "pending": sum(result["final_info"]["vehicles_pending"] for result in results),
        })
        self.flush()
        print(f"[검증] step={self.model.num_timesteps} mean_return={mean:.2f} best={self.best_score:.2f}", flush=True)

    def _on_step(self):
        for info in self.locals.get("infos", []):
            episode = info.get("episode")
            if episode:
                self.episode_count += 1
                self.writers["episodes"].writerow({
                    "global_step": self.num_timesteps, "episode": self.episode_count,
                    "episode_return": episode["r"], "episode_length": episode["l"],
                    "arrived": info["arrived_total"], "unfinished": info["vehicles_running"], "pending": info["vehicles_pending"],
                })
                self.flush()
        if self.num_timesteps % 100 == 0:
            self.writers["progress"].writerow({
                "global_step": self.num_timesteps, "optimizer_updates": self.model._n_updates,
                "exploration_rate": self.model.exploration_rate, "replay_size": self.model.replay_buffer.size(),
            })
            self.flush()
        if self.num_timesteps % 1000 == 0:
            print(f"[학습] step={self.num_timesteps} updates={self.model._n_updates} epsilon={self.model.exploration_rate:.3f}", flush=True)
        frequency = self.manifest["training_config"]["validation_frequency"]
        if self.num_timesteps % frequency == 0:
            self.validate()
        return True
