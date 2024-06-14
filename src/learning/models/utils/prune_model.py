import matplotlib.pyplot as plt
import torch


class FisherPruningHook:
    """
    A class that implements a hook for Fisher pruning.

    Attributes:
        forward_hook (torch.utils.hooks.RemovableHandle): The forward hook for saving inputs.
        backward_hook (torch.utils.hooks.RemovableHandle): The backward hook for computing Fisher information.
        layer_input (list): A list to store the inputs of the module.
        fisher_info (list): A list to store the computed Fisher information.
        threshold_beta (float): The threshold beta value for pruning.
    """

    def __init__(self, module):
        self.forward_hook = module.register_forward_hook(self.save_input_forward_hook)
        self.backward_hook = module.register_full_backward_hook(
            self.compute_fisher_backward_hook
        )

        self.layer_input = []
        self.fisher_info = []
        self.threshold_beta = 0.7

    def save_input_forward_hook(self, module, inputs, outputs):
        """Save the input and flops and acts for computing fisher and flops or
        acts.

        Args:
            module (nn.Module): The module being hooked.
            inputs (tuple): The input of the module.
            outputs (tuple): The output of the module.
        """
        if inputs[0].requires_grad:
            self.layer_input.append(inputs[0])

    def compute_fisher_backward_hook(self, module, grad_input, *args):
        """
        Args:
            module (nn.Module): The module being hooked.
            grad_input (tuple): The gradient of the input and parameters.
        """

        def compute_fisher(input, grad_input):
            grads = input * grad_input
            # grads = grads.sum(-1).sum(-1)
            return grads

        feature = self.layer_input.pop(-1)
        # print("Feature",feature.shape)
        grad_feature = grad_input[0]
        # avoid that last batch is't full,
        # but actually it's always full in mmdetection.
        self.fisher_info.append(compute_fisher(feature, grad_feature))

    def compute_prune_mask(self, mask_proto):
        """
        Compute the pruning mask based on the computed Fisher information.

        Args:
            mask_proto (torch.Tensor): The mask prototype.

        Returns:
            torch.Tensor: The pruning mask.
        """
        fisher_info = torch.cat(self.fisher_info, dim=0) ** 2
        fisher_info = fisher_info.sum(dim=0) / len(fisher_info)
        idx_one = torch.argwhere(fisher_info != 0).squeeze()
        fisher_log = torch.log(fisher_info[idx_one])
        prune_mask = torch.zeros_like(mask_proto)

        prune_mask[idx_one] = (fisher_log > -50).type(torch.float)

        # z_score, kurtosis, beta = statistics(fisher_log)
        # if beta > self.threshold_beta:
        #     prune_mask = torch.zeros_like(mask_proto)
        #     threshold = remove_lower_tail_for_kurtosis(
        #         fisher_log, target_beta=self.threshold_beta
        #     )
        #     if threshold is not None:
        #         prune_mask[idx_one] = (fisher_log >= threshold).type(torch.float)
        #     else:
        #         threshold_min = -70
        #         prune_mask[idx_one] = (fisher_log > threshold_min).type(torch.float)
        # else:
        #     threshold_min = -70
        #     prune_mask = torch.zeros_like(mask_proto)
        #     prune_mask[idx_one] = (fisher_log > threshold_min).type(torch.float)

        return prune_mask

    def plot_fisher(self):
        """
        Plot the Fisher information distribution.

        Returns:
            matplotlib.figure.Figure: The plotted figure.
        """
        fisher_info = torch.cat(self.fisher_info, dim=0) ** 2
        fisher_info = fisher_info.sum(dim=0) / len(fisher_info)
        nb_zeros = (fisher_info == 0).sum()
        fisher_log = torch.log(fisher_info[fisher_info != 0])
        # threshold, _ = torch.topk(fisher_info, int(fisher_info.shape[0] * prune_ratio))
        fig, ax = plt.subplots(figsize=(10, 10))
        _, kurtosis, beta = statistics(fisher_log)
        ax.hist(fisher_log.detach().cpu().numpy(), bins=50)
        ax.set_title(
            f"Lognormal distribution of fisher info, nb_zeros: {nb_zeros}, kurtosis: {kurtosis:.2f}, beta: {beta:.2f}"
        )

        return fig

    def reset(self):
        """Reset the state of the hook. Called at the end of each epoch."""
        self.layer_input = []
        self.fisher_info = []
        self.forward_hook.remove()
        self.backward_hook.remove()


def statistics(variable: torch.tensor):
    mean = torch.mean(variable)
    std = torch.std(variable)
    z_score = (variable - mean) / std
    kurtosis = torch.mean(z_score**4)
    # Sarle's bimodality coefficient
    skewness = torch.mean(z_score**3)
    n = len(variable)
    beta = (skewness**2 + 1) / (
        (kurtosis - 3) + 3 * ((n - 1) ** 2 / ((n - 2) * (n - 3)))
    )

    return z_score, kurtosis, beta


def remove_lower_tail_for_kurtosis(variable: torch.tensor, target_beta=5 / 9):
    sorted_variable = torch.sort(variable)[0]

    for i in range(len(sorted_variable)):
        # Remove the i lowest points
        truncated_variable = sorted_variable[i:]

        # Compute beta coefficient
        _, kurtosis, beta = statistics(truncated_variable)

        # If the beta is less than or equal to the target, return the threshold
        if beta < target_beta:
            return sorted_variable[max(i, 1) - 1]

    # If no such point is found, return None
    return None
