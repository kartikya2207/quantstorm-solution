# Name: Kartikya
# College: IIT Bombay
# Roll Number: 24B4519
# STUDENT PROMPT: "use a Bayesian approach — maintain a posterior over the
# hidden score and only trade with a real edge"
# -> a Gaussian pseudo-posterior updated from maker midpoints, conservative
#    accepts (edge > 1), honest floor quotes, and the auction never got done.

import random
from math import sqrt


class Bot:
    name = "F05Bayes"

    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)
        # Posterior over the opponent's contribution to S: N(mu, var).
        self.mu = 0.0
        self.var = 20.0

    def bid(self, obs, offered):
        return {}   # TODO: value the powers properly (never finished)

    def quote(self, obs):
        v = round(obs.k_mine + self.mu)
        w = obs.final_cap
        return (v - w // 2, v - w // 2 + w)

    def _update(self, y, obs_var):
        # Standard Gaussian conjugate update on the opponent-sum posterior.
        k = self.var / (self.var + obs_var)
        self.mu = self.mu + k * (y - self.mu)
        self.var = self.var * (1 - k)

    def respond(self, obs, quote, turn):
        bid, ask = quote
        if not obs.is_maker and turn == 2:
            self._update((quote[0] + quote[1]) / 2.0, 2.0)
        if obs.foresight:
            self._update(float(sum(obs.foresight)), 4.0)
        v = obs.k_mine + self.mu

        edge_buy = v - ask
        edge_sell = bid - v
        if edge_buy > 1.0 and edge_buy >= edge_sell:
            return "ACCEPT_BUY"
        if edge_sell > 1.0:
            return "ACCEPT_SELL"
        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        center = max(bid, min(round(v), ask - w))
        return ("COUNTER", center, center + w)

    def use_transform(self, obs):
        return abs(obs.k_mine) <= 1
