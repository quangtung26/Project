import torch
import torch.nn as nn
import torch.nn.functional as F
import torchaudio


class VGGVox(nn.Module):
    def __init__(self, n_out=1024, encoder_type='SAP', log_input=True, n_mels=40, **kwargs):
        super(VGGVox, self).__init__()

        print(f'Embedding size is {n_out}, encoder {encoder_type}.')

        self.encoder_type = encoder_type
        self.log_input = log_input
        self.n_mels = n_mels

        # Define CNN layers
        self.netcnn = nn.Sequential(
            nn.Conv2d(1, 96, kernel_size=(5,7), stride=(1,2), padding=(2,2)),
            nn.BatchNorm2d(96),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(1,3), stride=(1,2)),

            nn.Conv2d(96, 256, kernel_size=(5,5), stride=(2,2), padding=(1,1)),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(3,3), stride=(2,2)),

            nn.Conv2d(256, 384, kernel_size=(3,3), padding=(1,1)),
            nn.BatchNorm2d(384),
            nn.ReLU(inplace=True),

            nn.Conv2d(384, 256, kernel_size=(3,3), padding=(1,1)),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),

            nn.Conv2d(256, 256, kernel_size=(3,3), padding=(1,1)),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(3,3), stride=(2,2)),

            nn.Conv2d(256, 512, kernel_size=(4,1), padding=(0,0)),
            nn.BatchNorm2d(512),
            nn.ReLU(inplace=True)
        )

        # Initialize encoder
        if self.encoder_type == "MAX":
            self.encoder = nn.AdaptiveMaxPool2d((1,1))
            out_dim = 512
        elif self.encoder_type == "TAP":
            self.encoder = nn.AdaptiveAvgPool2d((1,1))
            out_dim = 512
        elif self.encoder_type == "SAP":
            self.sap_linear = nn.Linear(512, 512)
            self.attention = self.new_parameter(512, 1)
            out_dim = 512
        else:
            raise ValueError('Undefined encoder')

        # Initialize fully connected layer
        self.fc = nn.Linear(out_dim, n_out)

        # Initialize audio transform
        self.instancenorm = nn.InstanceNorm1d(40)
        self.torchfb      = torchaudio.transforms.MelSpectrogram(sample_rate=16000, n_fft=512, win_length=400, hop_length=160, f_min=0.0, f_max=8000, pad=0, n_mels=self.n_mels)

    def new_parameter(self, *size):
        """
        creates a new tensor 
        and initializes its values using the 
        Xavier normal initialization method.

        Args
        ----
            *size: specify the size of the tensor to be created

        Return
        ----
            out:  the initialized tensor
        """
        out = nn.Parameter(torch.FloatTensor(*size))
        nn.init.xavier_normal_(out)
        return out

    def forward(self, x):
        # disable gradient tracking and mixed-precision training
        with torch.no_grad():
            with torch.cuda.amp.autocast(enabled=False):
                x = self.torchfb(x)+1e-6
                if self.log_input: 
                    x = x.log()
                x = self.instancenorm(x).unsqueeze(1)
        x = self.netcnn(x)
        if self.encoder_type == "MAX" or self.encoder_type == "TAP":
            x = self.encoder(x)
            x = x.view((x.size()[0], -1))
        elif self.encoder_type == "SAP":
            x = x.permute(0, 2, 1, 3)
            x = x.squeeze(dim=1).permute(0, 2, 1)  # batch * L * D
            h = torch.tanh(self.sap_linear(x))
            w = torch.matmul(h, self.attention).squeeze(dim=2)
            w = F.softmax(w, dim=1).view(x.size(0), x.size(1), 1)
            x = torch.sum(x * w, dim=1)
        x = self.fc(x)
        return x


def model_init(n_out=1024, encoder_type='SAP', log_input=True, **kwargs):
    return VGGVox(n_out=n_out, encoder_type=encoder_type, log_input=log_input, **kwargs)