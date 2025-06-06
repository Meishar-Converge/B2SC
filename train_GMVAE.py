import torch
import numpy as np
import umap
import matplotlib.pyplot as plt
import torch.nn.functional as F
from pathlib import Path
from termcolor import colored

def zinb_loss(y_true, y_pred, pi, r, eps=1e-10):
    y_true = y_true.float()
    y_pred = y_pred.float()
    
    # Negative binomial part
    nb_case = -torch.lgamma(r + eps) + torch.lgamma(y_true + r + eps) - torch.lgamma(y_true + 1.0) \
              + r * torch.log(pi + eps) + y_true * torch.log(1.0 - (pi + eps))
    
    # Zero-inflated part
    zero_nb = torch.pow(pi, r)
    zero_case = torch.where(y_true < eps, -torch.log(zero_nb + (1.0 - zero_nb) * torch.exp(-r * torch.log(1.0 - pi + eps))), torch.tensor(0.0, device=y_true.device))
    
    return -torch.mean(zero_case + nb_case)


def train_GMVAE(model, epoch, dataloader, optimizer, proportion_tensor, kl_weight, mapping_dict, color_map, max_epochs, device='cuda', base_dir=None, plot_umap=False):
    assert base_dir is not None
    assert(isinstance(base_dir, str) or isinstance(base_dir, Path))
    model.train()
    total_loss = 0
    model = model.to(device)

    for idx, (data, labels) in enumerate(dataloader):
        # mask = data != 0
        # nonzero_idx = mask.nonzero(as_tuple=False)
        # assert nonzero_idx.size(0) > 0, "ERROR: got an all-zero data batch!"
        data = data.to(device)
        labels = labels.to(device)

        optimizer.zero_grad()
        reconstructed, mus, logvars, pis, zs = model(data, labels)
        if epoch == 0 and idx == 0:
            print("************************************* First batch of data: *************************************************")
            print("reconstructed.shape:", reconstructed.shape)
            print("data.shape:", data.shape)
            print("mus.shape:", mus.shape)
            print("logvars.shape:", logvars.shape)
            print("pis.shape:", pis.shape)
            print("zs.shape:", zs.shape)
        
        assert(reconstructed.shape == data.shape)
        
        proportion_tensor_reshaped = proportion_tensor.to(pis.device)
        # import pdb; pdb.set_trace()

        fraction_loss =  F.mse_loss(pis.mean(0), proportion_tensor_reshaped)
        loss_recon = F.mse_loss(reconstructed, data)


        # print(data.shape, reconstructed.shape)
        # print(model.module.prob_extra_zero.shape)
        # print(model.module.over_disp.shape)

        zinb_loss_val = zinb_loss(data, reconstructed, model.module.prob_extra_zero, model.module.over_disp)

        loss_kl = (0.5 * torch.sum(-1 - logvars + mus.pow(2) + logvars.exp())/1e9)
        loss_kl_weighted = loss_kl * kl_weight
        loss_kl_weighted = 1 if loss_kl_weighted > 1 else loss_kl_weighted
        
        loss = loss_recon*5 +  zinb_loss_val + (fraction_loss*10) + loss_kl_weighted
        loss.backward()

        # for name, param in model.named_parameters():
        #     if param.grad is not None:
        #         grad_norm = param.grad.norm().item()
        #         print(f"Grad | {name:30}: {grad_norm:.4e}")

        optimizer.step()
        print(colored(f"Loss: {loss.item():.4f}", 'magenta'))
        total_loss += loss.item()
    
    print(colored(f"fraction_loss: {fraction_loss:.4f}", 'cyan'))
    print(colored(f"loss_kl  unweighted: {loss_kl:.4f}", 'blue'))
    print(colored(f"loss_kl  weighted: {loss_kl_weighted:.4f}", 'blue'))
    print(colored(f"kl_weight: {kl_weight:.4f}", 'blue'))
    print(colored(f"loss_recon: {loss_recon:.4f}", 'blue'))
    print("Epoch finished")

    if ((epoch+1) % 10 == 0) and (epoch != max_epochs - 1):
        print("Saving intermediate results to folder:", base_dir)
        print(f'Epoch: {epoch+1} KL Loss: {loss_kl:.4f}\n Recon Loss: {loss_recon:.4f}\n Total Loss: {total_loss:.4f}\n Fraction Loss: {fraction_loss:.4f}\n ZINB Loss: {zinb_loss_val:.4f}')

        # Save reconstructed.
        print("Saving reconstructed to folder:", base_dir)
        torch.save(reconstructed, base_dir + '/GMVAE_reconstructed.pt')

        mus = mus.mean(0)
        logvars = logvars.mean(0)
        pis = pis.mean(0)
        
        # Save the mean, logvar, and pi.
        print("Saving mus, logvars, and pis to folder:", base_dir)
        torch.save(mus, base_dir + '/GMVAE_mus.pt')
        torch.save(logvars, base_dir + '/GMVAE_logvars.pt')
        torch.save(pis, base_dir + '/GMVAE_pis.pt')
        print("GMVAE mu & var & pi saved.")

        model.eval()
        torch.save(model.state_dict(), base_dir + 'GMVAE_model.pt')
        print("GMVAE Model saved.")

        if plot_umap:
            print("Plotting UMAP...")
            k = labels.cpu().detach().numpy()
            
            # Generate QQ plot for reconstructed data.
            reconstructed = reconstructed.cpu().detach().numpy()

            z = zs.cpu().detach().numpy()

            # Convert all_labels to colors using the color_map
            label_map = {str(v): k for k, v in mapping_dict.items()}
            mean_colors = [color_map[label_map[str(label.item())]] for label in k]
            z_colors = [color_map[label_map[str(label.item())]] for label in k]

            # UMAP transformation of recon
            reducer = umap.UMAP()
            embedding_z = reducer.fit_transform(z)
            embedding_recon = reducer.fit_transform(reconstructed)
    

            plt.figure(figsize=(12, 10))
            plt.scatter(embedding_z[:, 0], embedding_z[:, 1], c=z_colors, s=5)
            # Remove ticks
            plt.xticks([])
            plt.yticks([])
            # Name the axes.
            plt.xlabel('UMAP1')
            plt.ylabel('UMAP2')
            plt.title('UMAP of reparameterized z')
            plt.savefig(base_dir + 'umap_latent.png')
            plt.close()

            plt.figure(figsize=(12, 10))
            plt.scatter(embedding_recon[:, 0], embedding_recon[:, 1], c=mean_colors, s=5)
            # Remove ticks
            plt.xticks([])
            plt.yticks([])
            # Name the axes.
            plt.xlabel('UMAP1')
            plt.ylabel('UMAP2')
            plt.title('UMAP of Reconstructed Data')
            plt.savefig(base_dir + 'umap_recon.png')
            plt.close()

    elif epoch == max_epochs - 1:
        print(colored(f"Saving final results to folder: {base_dir}", 'green'))
        

        print(f'Epoch: {epoch+1} KL Loss: {loss_kl:.4f}\n Recon Loss: {loss_recon:.4f}\n Total Loss: {total_loss:.4f}\n Fraction Loss: {fraction_loss:.4f}\n ZINB Loss: {zinb_loss_val:.4f}')

        # Save reconstructed.
        print("Saving reconstructed to folder:", base_dir)
        torch.save(reconstructed, base_dir + 'GMVAE_reconstructed.pt')

        mus = mus.mean(0)
        logvars = logvars.mean(0)
        pis = pis.mean(0)

        # Save the mean, logvar, and pi.
        print("Saving mus, logvars, and pis to folder:", base_dir)
        torch.save(mus, base_dir + '/GMVAE_mus.pt')
        torch.save(logvars, base_dir + '/GMVAE_logvars.pt')
        torch.save(pis, base_dir + '/GMVAE_pis.pt')
        print("GMVAE mu & var & pi saved.")

        model.eval()
        torch.save(model.state_dict(), base_dir + '/GMVAE_model.pt')
        print("GMVAE Model saved.")
    
    return total_loss