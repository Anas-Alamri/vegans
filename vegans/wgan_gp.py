import torch


class WGANGP:
    def __init__(self, generator, discriminator, nz=100):
        self.generator = generator
        self.discriminator = discriminator
        self.nz = nz

    def train(self,
              dataloader,
              ngpu=0,
              optimizer_D=None,
              optimizer_G=None,
              num_epochs=5,
              fixed_noise_size=64,
              print_every=50,
              save_every=500,
              critic_iters=5,
              long_critic_iters=100,
              lambda_gp=10):
        """
        TODO: checkpointing

        :param dataloader:
        :param ngpu:
        :param optimizer_D:
        :param optimizer_G:
        :param num_epochs:
        :param fixed_latent_batch_size:
        :param init_weights:
        :param print_every: print every [print_every] mini batches within an epoch
        :param save_every: save generated samples every [save_every] iterations. In addition, it also saves
                           samples generated during the last mini batch.
        :return:
        """

        device = torch.device("cuda:0" if (torch.cuda.is_available() and ngpu > 0) else "cpu")

        def _grad_penalty(real, fake):
            assert real.size() == fake.size(), 'real and fake mini batches must have same size'
            batch_size = real.size(0)
            epsilon = torch.rand(batch_size, *[1 for _ in real.dim()], device=device)
            x_hat = (epsilon * real + (1. - epsilon) * fake).requires_grad_(True)
            output = self.discriminator(x_hat)
            grads = torch.autograd.grad(
                outputs=output,
                inputs=x_hat,
                grad_outputs=torch.ones((batch_size,), device=device)
            )[0]
            return ((grads.norm(2, dim=1) - 1) ** 2).mean()

        # Create batch of latent vectors that we will use to generate samples
        fixed_noise = torch.randn(fixed_noise_size, self.nz, device=device)

        """ Default optimizers for G and D
            TODO: abstract function?
        """
        if optimizer_D is None:
            optimizer_D = torch.optim.Adam(self.discriminator.parameters(), lr=0.0002, betas=(0.5, 0.999))
        if optimizer_G is None:
            optimizer_G = torch.optim.Adam(self.generator.parameters(), lr=0.0002, betas=(0.5, 0.999))

        """ Training Loop
        """
        # Structures keep track of progress. <(epoch, mini_batch), value>
        samples_list = dict()
        G_losses = dict()
        D_losses = dict()

        iters = 0
        gen_iters = 0

        print("Starting training Loop...")
        for epoch in range(num_epochs):
            for i, (data, _) in enumerate(dataloader):

                # the number of mini batches we'll train the critic before training the generator
                if gen_iters < 25 or gen_iters % 500 == 0:
                    D_iters = long_critic_iters
                else:
                    D_iters = critic_iters

                real = data.to(device)
                batch_size = real.size(0)

                """ Train the critic
                """
                optimizer_D.zero_grad()
                noise = torch.randn(batch_size, self.nz, device=device)
                fake = self.generator(noise).detach()

                loss_D = self.discriminator(fake) - self.discriminator(real) + lambda_gp * _grad_penalty(real, fake)
                D_losses[(epoch, i)] = loss_D.item()

                loss_D.backward()
                optimizer_D.step()

                if iters % D_iters == 0:
                    """ Train the generator every [Diters]
                    """
                    optimizer_G.zero_grad()
                    fake = self.generator(noise)
                    loss_G = -torch.mean(self.discriminator(fake))
                    G_losses[(epoch, i)] = loss_G.item()
                    loss_G.backward()
                    optimizer_G.step()
                    gen_iters += 1

                # Output training stats
                if i % print_every == 0:
                    last_G_loss = G_losses[max(G_losses.keys())] if len(G_losses) > 0 else float('nan')
                    print('[%d/%d][%d/%d]\tLoss_D: %.4f\tLoss_G: %.4f' % (epoch, num_epochs, i, len(dataloader),
                          loss_D.item(), last_G_loss))

                # Check how the generator is doing by saving G's output on fixed_noise
                if (iters % save_every == 0) or ((epoch == num_epochs - 1) and (i == len(dataloader) - 1)):
                    with torch.no_grad():
                        fake = self.generator(fixed_noise).detach().cpu()
                    # samples_list.append(vutils.make_grid(fake, padding=2, normalize=True))
                    samples_list[(epoch, i)] = fake

                iters += 1

        return samples_list, G_losses, D_losses